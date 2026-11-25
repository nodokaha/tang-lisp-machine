package org.tanglisp.companion

import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import java.security.MessageDigest

/**
 * FPGA config-flash writer: burns a raw flash image (the
 * fs2flash.py output) into the GW5A's external SPI NOR
 * (XTX XT25F64B) through the dock's BL616 debugger, speaking
 * MPSSE/JTAG on FT2232 channel A (interface 0, bulk 0x02/0x81).
 *
 * This is a faithful port of the hardware-proven Termux/Python
 * driver (flash_write6.py). The BL616 quirks are all load-bearing:
 *  - the TAP latches IR values shifted by one bit, so instruction
 *    codes are sent << 1;
 *  - a USB reset cures the MPSSE input path when it sticks;
 *  - the last byte reconstructed from a bridge read transaction
 *    is unreliable, so reads ask for one extra byte and drop it;
 *  - RDSR WEL/WIP bits do not read back over this bridge, so the
 *    flow uses fixed worst-case waits plus a full read-back
 *    verify instead of status polling.
 *
 * The debugger itself is never written; only the FPGA's config
 * flash is erased/programmed, and it can always be re-burned
 * through this same path.
 */
class FlashException(message: String) : Exception(message)

class JtagPort(private val manager: UsbManager, private val device: UsbDevice) {

    private var conn: UsbDeviceConnection? = null
    private var iface: UsbInterface? = null
    private var epOut: UsbEndpoint? = null
    private var epIn: UsbEndpoint? = null

    fun open() {
        close()
        val c = manager.openDevice(device) ?: throw FlashException("could not open USB device")
        conn = c
        val f = device.getInterface(0)
        iface = f
        if (!c.claimInterface(f, true)) {
            throw FlashException("could not claim JTAG interface")
        }
        findEndpoints()
    }

    private fun findEndpoints() {
        val f = iface ?: throw FlashException("no interface")
        for (i in 0 until f.endpointCount) {
            val ep = f.getEndpoint(i)
            if (ep.type != android.hardware.usb.UsbConstants.USB_ENDPOINT_XFER_BULK) continue
            if (ep.direction == android.hardware.usb.UsbConstants.USB_DIR_OUT) epOut = ep
            if (ep.direction == android.hardware.usb.UsbConstants.USB_DIR_IN) epIn = ep
        }
        if (epOut == null || epIn == null) throw FlashException("bulk endpoints not found")
    }

    /** USB reset cures the BL616's stuck MPSSE input path. After a
     *  reset the claim drops, so re-open from scratch.
     *  UsbDeviceConnection.resetDevice() is a system API (not in the
     *  SDK stubs), so call it reflectively and fall back to a plain
     *  re-open when the platform refuses. */
    fun resetAndReopen() {
        try {
            val m = conn?.javaClass?.getMethod("resetDevice")
            m?.invoke(conn)
        } catch (_: Exception) {
            // Hidden-API refusal or not present: the re-open below
            // plus the flow's own IDCODE retry still apply.
        }
        Thread.sleep(2000)
        open()
    }

    fun control(request: Int, value: Int, index: Int) {
        conn?.controlTransfer(0x40, request, value, index, null, 0, 1000)
    }

    /** FTDI/MPSSE session init (same transfers as the Python driver). */
    fun mpsseInit() {
        control(0x0B, 0x0000, 1)
        control(0x0B, 0x0200, 1)
        control(0x09, 2, 1) // latency timer 2 ms
        readPayload() // discard whatever the init produced
    }

    fun writeRaw(data: ByteArray) {
        val c = conn ?: throw FlashException("not open")
        val ep = epOut ?: throw FlashException("no OUT endpoint")
        var off = 0
        while (off < data.size) {
            val n = c.bulkTransfer(ep, data, off, data.size - off, 2000)
            if (n < 0) throw FlashException("bulk OUT failed")
            off += n
        }
    }

    /** Read FTDI packets until the FA AA terminator (the response
     *  to the 0xAA bad-command marker) or the deadline. Each USB
     *  packet's first two bytes are the FTDI status header. */
    fun readPayload(deadlineMs: Long = 3000): ByteArray {
        val c = conn ?: return ByteArray(0)
        val ep = epIn ?: return ByteArray(0)
        val out = mutableListOf<Byte>()
        val buf = ByteArray(512)
        val end = System.currentTimeMillis() + deadlineMs
        while (System.currentTimeMillis() < end) {
            val n = try {
                c.bulkTransfer(ep, buf, buf.size, 300)
            } catch (e: Exception) {
                -1
            }
            if (n > 2) {
                for (i in 2 until n) out.add(buf[i])
                if (out.size >= 2 &&
                    out[out.size - 2] == 0xFA.toByte() &&
                    out[out.size - 1] == 0xAA.toByte()
                ) break
            }
        }
        return ByteArray(out.size) { out[it] }
    }

    fun close() {
        try { conn?.releaseInterface(iface) } catch (_: Exception) {}
        try { conn?.close() } catch (_: Exception) {}
        conn = null
        iface = null
        epOut = null
        epIn = null
    }
}

class Gw5aFlasher(
    private val port: JtagPort,
    private val log: (String) -> Unit,
    private val progress: (String, Int) -> Unit
) {
    @Volatile var cancelled = false

    private val buf = mutableListOf<Byte>()

    companion object {
        const val IDCODE_GW5A = 0x0001281B
        val EXPECTED_JEDEC = byteArrayOf(0x0B, 0x40, 0x17, 0x08)

        private const val NOOP = 0x02
        private const val ERASE_SRAM = 0x05
        private const val XFER_DONE = 0x09
        private const val READ_IDCODE = 0x11
        private const val READ_STATUS = 0x41
        private const val CONFIG_ENABLE = 0x15
        private const val CONFIG_DISABLE = 0x3A
        private const val RELOAD = 0x3C

        private const val BIT_CRC_ERROR = 1 shl 0
        private const val BIT_BAD_COMMAND = 1 shl 1
        private const val BIT_TIMEOUT = 1 shl 3
        private const val BIT_AUTOBOOT2 = 1 shl 4
        private const val BIT_MEMORY_ERASE = 1 shl 5
        private const val BIT_EDIT_MODE = 1 shl 7
        private const val BIT_DONE = 1 shl 13
    }

    private fun checkCancel() {
        if (cancelled) throw FlashException("cancelled by user")
    }

    // ---- MPSSE primitives (mirror the Python Jtag class) ----

    private fun cmd(vararg bs: Int) {
        for (b in bs) buf.add(b.toByte())
    }

    private fun tmsBits(bits: List<Int>) {
        var i = 0
        while (i < bits.size) {
            val chunk = bits.subList(i, minOf(i + 6, bits.size))
            var v = 0
            for (j in chunk.indices) v = v or ((chunk[j] and 1) shl j)
            cmd(0x4B, chunk.size - 1, v)
            i += chunk.size
        }
    }

    private fun toggleClk(n0: Int) {
        var n = n0
        while (n > 0) {
            val k = minOf(7, n)
            cmd(0x4B, k - 1, 0x00)
            n -= k
        }
    }

    private fun shift(data: ByteArray, nbits: Int) {
        val nbytes = nbits / 8
        val rem = nbits % 8
        if (nbytes > 0) {
            cmd(0x39, (nbytes - 1) and 0xFF, ((nbytes - 1) shr 8) and 0xFF)
            for (i in 0 until nbytes) {
                buf.add(if (i < data.size) data[i] else 0)
            }
        }
        if (rem > 0) {
            val v = if (nbytes < data.size) data[nbytes].toInt() and 0xFF else 0
            cmd(0x3B, rem - 1, v and ((1 shl rem) - 1))
        }
    }

    private fun flush(): ByteArray {
        cmd(0xAA, 0x87)
        port.writeRaw(ByteArray(buf.size) { buf[it] })
        buf.clear()
        Thread.sleep(50)
        val pl = port.readPayload()
        return if (pl.size >= 2 &&
            pl[pl.size - 2] == 0xFA.toByte() && pl[pl.size - 1] == 0xAA.toByte()
        ) {
            pl.copyOfRange(0, pl.size - 2)
        } else {
            pl
        }
    }

    private fun resetTap() {
        tmsBits(listOf(1, 1, 1, 1, 1))
        tmsBits(listOf(0))
        flush()
    }

    private fun shiftIr(value: Int) {
        tmsBits(listOf(1, 1, 0, 0))
        shift(byteArrayOf(((value shl 1) and 0xFF).toByte()), 8)
        tmsBits(listOf(1, 1, 0))
    }

    private fun shiftDr(data: ByteArray, nbits: Int) {
        tmsBits(listOf(1, 0, 0))
        shift(data, nbits)
        tmsBits(listOf(1, 1, 0))
    }

    private fun sendCommand(code: Int) {
        shiftIr(code)
        toggleClk(6)
        flush()
    }

    private fun readReg32(code: Int): Int {
        sendCommand(code)
        shiftDr(byteArrayOf(-1, -1, -1, -1), 32)
        val data = flush()
        if (data.size < 4) {
            log("read_reg32 0x%02x short read (%d bytes)".format(code, data.size))
            return 0
        }
        return (data[0].toInt() and 0xFF) or
            ((data[1].toInt() and 0xFF) shl 8) or
            ((data[2].toInt() and 0xFF) shl 16) or
            ((data[3].toInt() and 0xFF) shl 24)
    }

    private fun readStatus(): Int = readReg32(READ_STATUS)

    private fun poll(mask: Int, value: Int, tag: String, tries: Int = 300): Boolean {
        var last = 0
        for (i in 0 until tries) {
            checkCancel()
            last = readStatus()
            if (last and mask == value) {
                log("poll %s ok: status=0x%08x".format(tag, last))
                return true
            }
            Thread.sleep(20)
        }
        log("poll %s TIMEOUT: last status=0x%08x".format(tag, last))
        return false
    }

    private fun enableCfg(): Boolean {
        sendCommand(CONFIG_ENABLE)
        return poll(BIT_EDIT_MODE, BIT_EDIT_MODE, "edit-mode on")
    }

    private fun disableCfg(): Boolean {
        sendCommand(CONFIG_DISABLE)
        sendCommand(NOOP)
        return poll(BIT_EDIT_MODE, 0, "edit-mode off")
    }

    // ---- GW5A SPI bridge (bit-banged through the TAP) ----

    private fun rev8(b: Int): Int {
        var x = b and 0xFF
        var r = 0
        repeat(8) {
            r = (r shl 1) or (x and 1)
            x = x shr 1
        }
        return r
    }

    private fun tmsTdi(bits: List<Int>, tdi: Boolean) {
        var i = 0
        while (i < bits.size) {
            val chunk = bits.subList(i, minOf(i + 7, bits.size))
            var v = 0
            for (k in chunk.indices) v = v or ((chunk[k] and 1) shl k)
            if (tdi) v = v or 0x80
            cmd(0x4B, chunk.size - 1, v)
            i += chunk.size
        }
    }

    /** One SPI transaction. rxTotal == null: write-only. Otherwise
     *  returns rxTotal reconstructed bytes (see the Python driver
     *  for the +3-bit capture offset this mirrors). */
    private fun spiPut(command: Int, tx: ByteArray?, rxTotal: Int?): ByteArray? {
        val txb = tx ?: ByteArray(0)
        val rc = rev8(command)
        val totalBits = if (rxTotal == null) txb.size * 8 else rxTotal * 8 + 3
        tmsTdi(listOf(0), (rc and 1) != 0) // CS falls, first cmd bit on TDI
        shift(byteArrayOf((rc shr 1).toByte()), 7)
        val stream = mutableListOf<Byte>()
        for (b in txb) stream.add(rev8(b.toInt()).toByte())
        val lastBit = if (txb.isNotEmpty()) (txb[txb.size - 1].toInt() and 1) else (command and 1)
        val nbytes = totalBits / 8
        val rembits = totalBits % 8
        val need = nbytes + if (rembits > 0) 1 else 0
        while (stream.size < need) stream.add(if (lastBit != 0) 0xFF.toByte() else 0)
        if (nbytes > 0) shift(ByteArray(nbytes) { stream[it] }, nbytes * 8)
        if (rembits > 0) shift(byteArrayOf(stream[nbytes]), rembits)
        tmsTdi(List(8) { 1 }, lastBit != 0) // CS rises
        val cap = flush()
        if (rxTotal == null) return null
        val body = cap.copyOfRange(1, cap.size)
        if (body.size < rxTotal + 1) {
            log("spi_put 0x%02x short capture: cap=%d".format(command, cap.size))
            return null
        }
        val out = ByteArray(rxTotal)
        for (i in 0 until rxTotal) {
            val hi = (body[i].toInt() and 0xFF) shr 3
            val lo = (body[i + 1].toInt() and 0x07) shl 5
            out[i] = rev8((hi or lo) and 0xFF).toByte()
        }
        return out
    }

    private fun exitSpiDance() {
        tmsBits(List(16) { 1 })
        val bits = mutableListOf(0, 1, 0, 1, 0, 1)
        repeat(6) { bits.addAll(listOf(0, 1, 0, 1)) }
        bits.addAll(listOf(0, 1, 0))
        tmsBits(bits)
        tmsBits(List(16) { 1 })
        toggleClk(5)
        flush()
    }

    private fun fail(msg: String): Nothing {
        try { exitSpiDance() } catch (_: Exception) {}
        throw FlashException(msg)
    }

    // ---- flash helpers (fixed waits; see the class docs) ----

    private fun fRead(addr0: Int, n0: Int, onProgress: ((Int) -> Unit)? = null): ByteArray? {
        var addr = addr0
        var n = n0
        val out = mutableListOf<Byte>()
        while (n > 0) {
            checkCancel()
            val k = minOf(n, 256)
            var r: ByteArray? = null
            for (attempt in 0 until 3) {
                val tx = ByteArray(3 + k + 1)
                tx[0] = ((addr shr 16) and 0xFF).toByte()
                tx[1] = ((addr shr 8) and 0xFF).toByte()
                tx[2] = (addr and 0xFF).toByte()
                r = spiPut(0x03, tx, 3 + k + 1)
                if (r != null && r.size >= 3 + k + 1) break
                log("read retry @0x%x".format(addr))
            }
            if (r == null || r.size < 3 + k + 1) return null
            for (i in 3 until 3 + k) out.add(r[i])
            addr += k
            n -= k
            onProgress?.invoke(out.size)
        }
        return ByteArray(out.size) { out[it] }
    }

    private fun fWren() {
        spiPut(0x06, null, null)
    }

    private fun addrBytes(addr: Int) = byteArrayOf(
        ((addr shr 16) and 0xFF).toByte(),
        ((addr shr 8) and 0xFF).toByte(),
        (addr and 0xFF).toByte()
    )

    private fun fBlockErase(addr: Int) {
        fWren()
        spiPut(0xD8, addrBytes(addr), null)
        Thread.sleep(2500)
    }

    private fun fPageProgram(addr: Int, chunk: ByteArray) {
        fWren()
        spiPut(0x02, addrBytes(addr) + chunk, null)
        Thread.sleep(12)
    }

    private fun md5(data: ByteArray): String {
        val d = MessageDigest.getInstance("MD5").digest(data)
        return d.joinToString("") { "%02x".format(it) }
    }

    // ---- the burn flow (flash_write6.py, step for step) ----

    fun burn(image: ByteArray) {
        port.open()
        port.resetAndReopen()
        port.mpsseInit()
        // 1 MHz clock (divisor 5 on the 12 MHz base) + low-byte GPIO.
        cmd(0x86, 0x05, 0x00, 0x80, 0x08, 0x0B)
        flush()
        resetTap()

        var idc = readReg32(READ_IDCODE)
        if (idc != IDCODE_GW5A) {
            log("IDCODE not readable -> exit-spi dance")
            exitSpiDance()
            idc = readReg32(READ_IDCODE)
        }
        log("IDCODE = 0x%08x".format(idc))
        if (idc != IDCODE_GW5A) fail("idcode mismatch")
        val status0 = readStatus()
        log("STATUS start = 0x%08x DONE=%d".format(status0, if (status0 and BIT_DONE != 0) 1 else 0))

        progress("Preparing (reload + SRAM erase)", 0)
        sendCommand(RELOAD)
        sendCommand(NOOP)
        tmsBits(listOf(0))
        repeat(100) {
            toggleClk(10000)
            flush()
        }
        log("reload + 1M clocks done")

        var status = readStatus()
        if (status and (BIT_TIMEOUT or BIT_AUTOBOOT2 or BIT_BAD_COMMAND) != 0) {
            log("bad-state cleanup (0x3F)")
            sendCommand(CONFIG_ENABLE)
            sendCommand(0x3F)
            sendCommand(CONFIG_DISABLE)
            sendCommand(NOOP)
            sendCommand(READ_IDCODE)
            sendCommand(NOOP)
            toggleClk(1000)
            flush()
        }

        var loop = 0
        while (true) {
            checkCancel()
            if (!enableCfg()) fail("enable_cfg (sram erase)")
            sendCommand(ERASE_SRAM)
            sendCommand(NOOP)
            if (!poll(BIT_MEMORY_ERASE, BIT_MEMORY_ERASE, "memory-erase")) {
                fail("poll memory-erase")
            }
            sendCommand(XFER_DONE)
            sendCommand(NOOP)
            if (!disableCfg()) fail("disable_cfg (sram erase)")
            if (loop >= 1) {
                val s = readStatus()
                log("erase loop %d status=0x%08x DONE=%d".format(loop, s, if (s and BIT_DONE != 0) 1 else 0))
                if (s and BIT_DONE == 0) break
            }
            loop++
            if (loop > 6) fail("sram erase loop")
        }
        log("SRAM ERASED")

        if (!enableCfg()) fail("enable_cfg (spi)")
        sendCommand(0x3F)
        if (!disableCfg()) fail("disable_cfg (spi)")
        sendCommand(NOOP)
        toggleClk(1008)
        flush()
        sendCommand(0x16)
        sendCommand(0x00)
        toggleClk(5000)
        tmsBits(listOf(1, 1, 1, 1, 1))
        flush()
        log("SPI MODE ON")

        spiPut(0xFF, ByteArray(8) { -1 }, null)
        spiPut(0x66, null, null)
        spiPut(0x99, null, null)
        Thread.sleep(50)
        val jedec = spiPut(0x9F, null, 4)
        log("JEDEC: " + (jedec?.joinToString("") { "%02x".format(it) } ?: "null"))
        if (jedec == null || !jedec.contentEquals(EXPECTED_JEDEC)) fail("unexpected JEDEC")

        val imgMd5 = md5(image)
        val span = ((image.size + 0xFFFF) / 0x10000) * 0x10000
        log("image bytes: %d md5: %s erase span: %d".format(image.size, imgMd5, span))

        progress("Erasing", 2)
        fBlockErase(0x100000)
        val chk = fRead(0x100000, 32)
        if (chk == null || !chk.all { it == 0xFF.toByte() }) fail("scratch block erase did not produce 0xFF")
        log("BLOCK ERASE OK")

        val nblocks = span / 0x10000
        var addr = 0
        var bi = 0
        while (addr < span) {
            checkCancel()
            fBlockErase(addr)
            log("erased block @0x%05x".format(addr))
            addr += 0x10000
            bi++
            progress("Erasing block %d/%d".format(bi, nblocks), 2 + 8 * bi / nblocks)
        }
        val chk0 = fRead(0, 64)
        if (chk0 == null || !chk0.all { it == 0xFF.toByte() }) fail("span erase check failed @0")
        log("SPAN ERASED")

        val npages = (image.size + 255) / 256
        var lastPct = -1
        for (p in 0 until npages) {
            checkCancel()
            val a = p * 256
            var chunk = image.copyOfRange(a, minOf(a + 256, image.size))
            if (chunk.size < 256) chunk = chunk + ByteArray(256 - chunk.size) { 0xFF.toByte() }
            fPageProgram(a, chunk)
            val pct = 10 + 50 * (p + 1) / npages
            if (pct != lastPct) {
                lastPct = pct
                progress("Programming page %d/%d".format(p + 1, npages), pct)
            }
            if (p % 256 == 0) {
                log("programmed page %d/%d".format(p, npages))
            }
        }
        log("PROGRAM DONE")

        progress("Verifying", 60)
        val back = fRead(0, image.size) { done ->
            progress("Verifying", 60 + 40 * done / image.size)
        } ?: fail("verify read error")
        val backMd5 = md5(back)
        log("verify md5: %s (expect %s)".format(backMd5, imgMd5))
        if (!back.contentEquals(image)) {
            for (i in image.indices) {
                if (back[i] != image[i]) {
                    log("first mismatch @%d: flash=0x%02x want=0x%02x".format(i, back[i], image[i]))
                    break
                }
            }
            fail("verify mismatch")
        }
        log("VERIFY OK")

        exitSpiDance()
        sendCommand(RELOAD)
        sendCommand(NOOP)
        Thread.sleep(2000)
        val s = readStatus()
        log("STATUS after RELOAD = 0x%08x DONE=%d".format(s, if (s and BIT_DONE != 0) 1 else 0))
        progress("Done", 100)
        log("FLASH_WRITE_DONE")
    }
}

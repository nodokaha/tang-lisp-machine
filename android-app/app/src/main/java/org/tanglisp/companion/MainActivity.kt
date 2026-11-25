package org.tanglisp.companion

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import com.hoho.android.usbserial.util.SerialInputOutputManager
import java.io.IOException

/**
 * TangLisp companion v0: a USB serial console for the Tang Primer 25K dock.
 *
 * The dock's BL616 debugger enumerates as an FTDI FT2232 (VID 0x0403,
 * PID 0x6010). Port index 1 (channel B) is wired to the FPGA UART at
 * 115200 8N1. Established hardware fact: nothing flows until DTR is
 * asserted, so connect() sets DTR immediately after opening the port.
 */
class MainActivity : Activity(), SerialInputOutputManager.Listener {

    companion object {
        private const val ACTION_USB_PERMISSION = "org.tanglisp.companion.USB_PERMISSION"
        private const val VENDOR_ID = 0x0403
        private const val PRODUCT_ID = 0x6010
        private const val PORT_INDEX = 1 // FT2232 channel B = FPGA UART
        private const val BAUD = 115200
        private const val WRITE_TIMEOUT_MS = 1000
        private const val MAX_CONSOLE_CHARS = 32_000
        private const val REQ_PICK_FILE = 4101
        private const val REQ_PICK_FLASH = 4102
        private const val MAX_SEND_BYTES = 65_536
        private const val MAX_FLASH_BYTES = 8 * 1024 * 1024
    }

    private lateinit var statusText: TextView
    private lateinit var statusLamp: android.view.View
    private lateinit var consoleText: TextView
    private lateinit var consoleScroll: ScrollView
    private lateinit var inputField: EditText
    private lateinit var connectButton: Button

    private var port: UsbSerialPort? = null
    private var ioManager: SerialInputOutputManager? = null

    // ---- live world fetch: (dump) on the board answers with a
    // "WORLD-BEGIN <bytes>" line followed by the raw heap image.
    // Incoming serial data is diverted into the capture while a
    // fetch is in flight; everything else still reaches the console.
    private enum class Capture { IDLE, SEEKING, RECEIVING }

    @Volatile private var captureState = Capture.IDLE
    private val seekBuf = mutableListOf<Byte>()
    private var captureBuf: ByteArray? = null
    private var captureFilled = 0
    private val uiHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private var captureTimeout: Runnable? = null

    // ---- file send: the on-card Lisp driver (SDW1..6.LSP) receives
    // a file over the UART. Flow: (load SDWn.LSP) x6, then
    // (recv-file (quote (<11 name bytes>)) <len>) and wait for the
    // driver's STORE-READY line, stream the payload in paced
    // chunks, then wait for the result prompt.
    private enum class SendFlow { IDLE, LOAD_DRIVER, WAIT_READY, STREAM, WAIT_DONE }

    // ---- config flash burn (JTAG, see FlashWriter.kt) ----
    private var flasher: Gw5aFlasher? = null
    @Volatile private var flashRunning = false
    private var pendingFlashImage: ByteArray? = null
    private var pendingFlashAfterPermission = false
    private var wakeLock: android.os.PowerManager.WakeLock? = null
    private lateinit var flashButton: Button
    private lateinit var flashProgress: android.widget.ProgressBar

    @Volatile private var sendState = SendFlow.IDLE
    private var sendStep = 0
    private var sendPayload: ByteArray? = null
    private var sendName83: List<Int> = emptyList()
    private var sendDisplayName = ""
    private var sendOffset = 0
    private val rxScan = StringBuilder()
    private var sendTimeout: Runnable? = null

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val device: UsbDevice? = intent.parcelableExtra(UsbManager.EXTRA_DEVICE)
                    if (granted && device != null) {
                        if (pendingFlashAfterPermission) {
                            pendingFlashAfterPermission = false
                            startFlashBurn(device)
                        } else {
                            openPort(device)
                        }
                    } else {
                        pendingFlashAfterPermission = false
                        setStatus("USB permission denied")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device: UsbDevice? = intent.parcelableExtra(UsbManager.EXTRA_DEVICE)
                    if (device != null && device.vendorId == VENDOR_ID && device.productId == PRODUCT_ID) {
                        disconnect()
                        setStatus("Device detached")
                    }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        statusLamp = findViewById(R.id.statusLamp)
        consoleText = findViewById(R.id.consoleText)
        consoleScroll = findViewById(R.id.consoleScroll)
        inputField = findViewById(R.id.inputField)
        connectButton = findViewById(R.id.connectButton)

        connectButton.setOnClickListener {
            if (port != null) disconnect() else findAndConnect()
        }
        findViewById<Button>(R.id.worldButton).setOnClickListener {
            if (port != null) startWorldFetch()
            else startActivity(Intent(this, WorldActivity::class.java))
        }
        findViewById<Button>(R.id.sendFileButton).setOnClickListener {
            if (port == null) {
                setStatus("Not connected")
            } else if (sendState != SendFlow.IDLE) {
                setStatus("A file send is already running")
            } else {
                val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                }
                startActivityForResult(pick, REQ_PICK_FILE)
            }
        }
        flashProgress = findViewById(R.id.flashProgress)
        flashButton = findViewById(R.id.flashButton)
        flashButton.setOnClickListener {
            if (flashRunning) {
                flasher?.cancelled = true
                setStatus("Cancelling flash...")
                return@setOnClickListener
            }
            if (captureState != Capture.IDLE || sendState != SendFlow.IDLE) {
                setStatus("Another transfer is running")
                return@setOnClickListener
            }
            val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
            }
            startActivityForResult(pick, REQ_PICK_FLASH)
        }
        findViewById<Button>(R.id.sendButton).setOnClickListener { sendInput() }
        inputField.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendInput()
                true
            } else {
                false
            }
        }

        // Boot-launcher keys: digits go out as single bytes, no newline,
        // because the on-device menu reads exactly one keypress.
        val digitButtons = listOf(
            R.id.key0 to '0', R.id.key1 to '1', R.id.key2 to '2', R.id.key3 to '3',
            R.id.key4 to '4', R.id.key5 to '5', R.id.key6 to '6', R.id.key7 to '7',
            R.id.key8 to '8', R.id.key9 to '9'
        )
        for ((id, digit) in digitButtons) {
            findViewById<Button>(id).setOnClickListener { writeBytes(byteArrayOf(digit.code.toByte())) }
        }
        findViewById<Button>(R.id.keyEnter).setOnClickListener { writeBytes("\n".toByteArray()) }

        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(usbReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(usbReceiver, filter)
        }

        // Launched by plugging the dock in (USB_DEVICE_ATTACHED intent).
        val device: UsbDevice? = intent.parcelableExtra(UsbManager.EXTRA_DEVICE)
        if (device != null) {
            requestPermissionOrOpen(device)
        } else {
            findDevice()?.let { setStatus("Found FT2232 — tap Connect") }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val device: UsbDevice? = intent.parcelableExtra(UsbManager.EXTRA_DEVICE)
        if (device != null) requestPermissionOrOpen(device)
    }

    @Deprecated("framework-only app: the classic result callback is fine")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK) return
        if (requestCode != REQ_PICK_FILE && requestCode != REQ_PICK_FLASH) return
        val uri = data?.data ?: return
        val name = queryDisplayName(uri) ?: "FILE.BIN"
        val bytes = try {
            contentResolver.openInputStream(uri)?.use { it.readBytes() }
        } catch (e: Exception) {
            null
        }
        if (bytes == null) {
            setStatus("Could not read the picked file")
            return
        }
        if (requestCode == REQ_PICK_FILE) {
            startFileSend(name, bytes)
        } else {
            confirmFlash(name, bytes)
        }
    }

    // ---- config flash burn ----

    private fun md5Hex(data: ByteArray): String {
        val d = java.security.MessageDigest.getInstance("MD5").digest(data)
        return d.joinToString("") { "%02x".format(it) }
    }

    private fun confirmFlash(name: String, bytes: ByteArray) {
        if (bytes.isEmpty() || bytes.size > MAX_FLASH_BYTES) {
            setStatus("Bad flash image size: ${bytes.size}")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Burn config flash?")
            .setMessage(
                "$name\n${bytes.size} bytes\nMD5 ${md5Hex(bytes)}\n\n" +
                    "This erases and rewrites the FPGA config flash via JTAG " +
                    "(about 10 minutes). The board stops until the burn " +
                    "finishes and then boots the new image. The USB " +
                    "debugger itself is never written."
            )
            .setPositiveButton("Burn") { _, _ ->
                pendingFlashImage = bytes
                val device = findDevice()
                if (device == null) {
                    setStatus("FT2232 (0403:6010) not found")
                    pendingFlashImage = null
                } else {
                    val manager = getSystemService(UsbManager::class.java)
                    if (manager.hasPermission(device)) {
                        startFlashBurn(device)
                    } else {
                        pendingFlashAfterPermission = true
                        requestPermissionOrOpen(device)
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startFlashBurn(device: UsbDevice) {
        val image = pendingFlashImage ?: return
        pendingFlashImage = null
        if (port != null) {
            disconnect()
            appendConsole("\n[flash: console disconnected]\n")
        }
        val manager = getSystemService(UsbManager::class.java)
        val jtag = JtagPort(manager, device)
        val f = Gw5aFlasher(
            jtag,
            log = { line -> runOnUiThread { appendConsole("[flash] $line\n") } },
            progress = { phase, pct ->
                runOnUiThread {
                    flashProgress.progress = pct
                    setStatus("Flash: $phase ($pct%)")
                }
            }
        )
        flasher = f
        flashRunning = true
        flashButton.text = "Cancel flash"
        flashProgress.progress = 0
        flashProgress.visibility = android.view.View.VISIBLE
        // The wake lock is a nice-to-have (keep the CPU awake during
        // the ~10 min burn); never let it take the flow down.
        wakeLock = try {
            val pm = getSystemService(android.os.PowerManager::class.java)
            pm.newWakeLock(
                android.os.PowerManager.PARTIAL_WAKE_LOCK, "tanglisp:flash"
            ).apply { acquire(20 * 60 * 1000L) }
        } catch (e: Exception) {
            appendConsole("[flash] wake lock unavailable: ${e.message}\n")
            null
        }
        appendConsole("[flash: burning ${image.size} bytes, keep the app open]\n")
        setStatus("Flash: starting")
        Thread {
            var result: String? = null
            var error: String? = null
            try {
                f.burn(image)
                result = "Flash complete - board rebooted on the new image"
            } catch (e: FlashException) {
                error = e.message
            } catch (e: Exception) {
                error = "unexpected: ${e.message}"
            } finally {
                try { jtag.close() } catch (_: Exception) {}
            }
            runOnUiThread {
                flashRunning = false
                flasher = null
                flashButton.text = "Flash"
                flashProgress.visibility = android.view.View.GONE
                try { wakeLock?.release() } catch (_: Exception) {}
                wakeLock = null
                if (result != null) {
                    appendConsole("[flash] $result\n")
                    setStatus(result)
                } else {
                    appendConsole("[flash] FAILED: $error\n")
                    setStatus("Flash failed: $error")
                }
            }
        }.start()
    }

    private fun queryDisplayName(uri: android.net.Uri): String? {
        return try {
            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && cursor.moveToFirst()) cursor.getString(idx) else null
            }
        } catch (e: Exception) {
            null
        }
    }

    override fun onDestroy() {
        flasher?.cancelled = true
        disconnect()
        unregisterReceiver(usbReceiver)
        super.onDestroy()
    }

    // ---- connection handling ----

    private fun findDevice(): UsbDevice? {
        val manager = getSystemService(UsbManager::class.java)
        return manager.deviceList.values.firstOrNull {
            it.vendorId == VENDOR_ID && it.productId == PRODUCT_ID
        }
    }

    private fun findAndConnect() {
        val device = findDevice()
        if (device == null) {
            setStatus("FT2232 (0403:6010) not found")
            return
        }
        requestPermissionOrOpen(device)
    }

    private fun requestPermissionOrOpen(device: UsbDevice) {
        val manager = getSystemService(UsbManager::class.java)
        if (manager.hasPermission(device)) {
            openPort(device)
        } else {
            setStatus("Requesting USB permission…")
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                PendingIntent.FLAG_MUTABLE
            } else {
                0
            }
            val permissionIntent = PendingIntent.getBroadcast(
                this, 0, Intent(ACTION_USB_PERMISSION).setPackage(packageName), flags
            )
            manager.requestPermission(device, permissionIntent)
        }
    }

    private fun openPort(device: UsbDevice) {
        if (port != null) return
        val manager = getSystemService(UsbManager::class.java)
        val driver = UsbSerialProber.getDefaultProber().probeDevice(device)
        if (driver == null) {
            setStatus("No serial driver for this device")
            return
        }
        if (driver.ports.size <= PORT_INDEX) {
            setStatus("Device has ${driver.ports.size} port(s), need index $PORT_INDEX")
            return
        }
        val connection = manager.openDevice(device)
        if (connection == null) {
            setStatus("Could not open USB device")
            return
        }
        val serialPort = driver.ports[PORT_INDEX]
        try {
            serialPort.open(connection)
            serialPort.setParameters(
                BAUD,
                UsbSerialPort.DATABITS_8,
                UsbSerialPort.STOPBITS_1,
                UsbSerialPort.PARITY_NONE
            )
            // The BL616 UART bridge delivers nothing until DTR is on.
            serialPort.setDTR(true)
        } catch (e: IOException) {
            setStatus("Open failed: ${e.message}")
            try { serialPort.close() } catch (_: IOException) {}
            return
        }
        port = serialPort
        ioManager = SerialInputOutputManager(serialPort, this).also { it.start() }
        connectButton.text = "Disconnect"
        statusLamp.setBackgroundResource(R.drawable.lamp_on)
        setStatus("Connected: port $PORT_INDEX @ $BAUD 8N1, DTR on")
    }

    private fun disconnect() {
        sendState = SendFlow.IDLE
        sendTimeout?.let { uiHandler.removeCallbacks(it) }
        ioManager?.stop()
        ioManager = null
        try { port?.close() } catch (_: IOException) {}
        port = null
        connectButton.text = "Connect"
        if (::statusLamp.isInitialized) statusLamp.setBackgroundResource(R.drawable.lamp_off)
    }

    // ---- serial I/O ----

    override fun onNewData(data: ByteArray) {
        if (captureState == Capture.IDLE) {
            val text = String(data, Charsets.UTF_8)
            runOnUiThread { appendConsole(text) }
            if (sendState != SendFlow.IDLE) scanSendFlow(text)
        } else {
            handleCaptureData(data)
        }
    }

    // ---- live world fetch ----

    private fun startWorldFetch() {
        seekBuf.clear()
        captureBuf = null
        captureFilled = 0
        captureState = Capture.SEEKING
        appendConsole("\n[fetching world from board…]\n")
        writeBytes("(dump)\n".toByteArray())
        captureTimeout?.let { uiHandler.removeCallbacks(it) }
        val timeout = Runnable {
            if (captureState != Capture.IDLE) {
                captureState = Capture.IDLE
                appendConsole("[world fetch timed out]\n")
            }
        }
        captureTimeout = timeout
        uiHandler.postDelayed(timeout, 20_000)
    }

    private fun handleCaptureData(data: ByteArray) {
        if (captureState == Capture.SEEKING) {
            for (b in data) seekBuf.add(b)
            val buf = ByteArray(seekBuf.size) { seekBuf[it] }
            val marker = "WORLD-BEGIN ".toByteArray(Charsets.US_ASCII)
            val mi = indexOf(buf, marker)
            if (mi < 0) {
                // No marker yet: show text, keep a tail for a marker
                // split across chunks.
                val keep = marker.size - 1
                if (buf.size > keep) {
                    val flush = buf.copyOfRange(0, buf.size - keep)
                    runOnUiThread {
                        appendConsole(String(flush, Charsets.UTF_8))
                    }
                    seekBuf.clear()
                    for (k in buf.size - keep until buf.size) seekBuf.add(buf[k])
                }
                return
            }
            val nl = indexOfByte(buf, '\n'.code.toByte(), mi)
            if (nl < 0) return // marker line not complete yet
            val line = String(buf, mi, nl - mi, Charsets.US_ASCII)
            val total = line.removePrefix("WORLD-BEGIN ").trim().toIntOrNull()
            // The text before the marker and the marker line itself
            // belong in the console; the binary starts after the \n.
            val textPart = buf.copyOfRange(0, nl + 1)
            runOnUiThread { appendConsole(String(textPart, Charsets.UTF_8)) }
            seekBuf.clear()
            if (total == null || total <= 0 || total > 1_000_000) {
                captureState = Capture.IDLE
                runOnUiThread { appendConsole("[world fetch: bad size]\n") }
                return
            }
            captureBuf = ByteArray(total)
            captureFilled = 0
            captureState = Capture.RECEIVING
            // Remaining bytes in this chunk are the start of the image.
            feedCapture(buf.copyOfRange(nl + 1, buf.size))
            return
        }
        if (captureState == Capture.RECEIVING) {
            feedCapture(data)
        }
    }

    private fun feedCapture(bytes: ByteArray) {
        val buf = captureBuf ?: return
        var i = 0
        while (i < bytes.size && captureFilled < buf.size) {
            buf[captureFilled++] = bytes[i++]
        }
        if (captureFilled >= buf.size) {
            captureState = Capture.IDLE
            captureTimeout?.let { uiHandler.removeCallbacks(it) }
            WorldInbox.latest = buf
            val leftover = bytes.copyOfRange(i, bytes.size)
            runOnUiThread {
                appendConsole("[world received: ${buf.size} bytes]\n")
                if (leftover.isNotEmpty()) {
                    appendConsole(String(leftover, Charsets.UTF_8))
                }
                startActivity(Intent(this, WorldActivity::class.java))
            }
        }
    }

    private fun indexOf(haystack: ByteArray, needle: ByteArray): Int {
        if (needle.isEmpty() || haystack.size < needle.size) return -1
        for (i in 0..haystack.size - needle.size) {
            var ok = true
            for (j in needle.indices) {
                if (haystack[i + j] != needle[j]) { ok = false; break }
            }
            if (ok) return i
        }
        return -1
    }

    private fun indexOfByte(haystack: ByteArray, b: Byte, from: Int): Int {
        for (i in from until haystack.size) if (haystack[i] == b) return i
        return -1
    }

    // ---- file send (Lisp SD writer driver) ----

    private fun name83Of(displayName: String): List<Int> {
        val upper = displayName.uppercase()
        val dot = upper.lastIndexOf('.')
        val base = if (dot > 0) upper.substring(0, dot) else upper
        val ext = if (dot > 0) upper.substring(dot + 1) else ""
        fun clean(s: String) = s.map { c -> if (c in 'A'..'Z' || c in '0'..'9') c else '_' }
        val b = clean(base).take(8).joinToString("").padEnd(8, ' ')
        val e = clean(ext).take(3).joinToString("").padEnd(3, ' ')
        return (b + e).map { it.code }
    }

    private fun startFileSend(displayName: String, bytes: ByteArray) {
        if (port == null) {
            setStatus("Not connected")
            return
        }
        if (captureState != Capture.IDLE) {
            setStatus("World fetch is running")
            return
        }
        if (bytes.size > MAX_SEND_BYTES) {
            setStatus("File too large: ${bytes.size} bytes (max $MAX_SEND_BYTES)")
            return
        }
        sendPayload = bytes
        sendDisplayName = displayName
        sendName83 = name83Of(displayName)
        sendStep = 1
        sendOffset = 0
        rxScan.setLength(0)
        sendState = SendFlow.LOAD_DRIVER
        val shown = sendName83.map { it.toChar() }.joinToString("")
        appendConsole("\n[sending $displayName (${bytes.size} bytes) as $shown...]\n")
        if (bytes.size > 1279) {
            appendConsole("[note: over 1279 bytes - stored as data; the board cannot (load) it]\n")
        }
        writeBytes("(load SDW1.LSP)\n".toByteArray())
        armSendTimeout(20_000)
    }

    private fun armSendTimeout(ms: Long) {
        sendTimeout?.let { uiHandler.removeCallbacks(it) }
        val r = Runnable {
            if (sendState != SendFlow.IDLE) failSend("File send timed out")
        }
        sendTimeout = r
        uiHandler.postDelayed(r, ms)
    }

    private fun failSend(msg: String) {
        sendState = SendFlow.IDLE
        sendTimeout?.let { uiHandler.removeCallbacks(it) }
        runOnUiThread {
            appendConsole("[$msg]\n")
            setStatus(msg)
        }
    }

    private val streamChunk = object : Runnable {
        override fun run() {
            if (sendState != SendFlow.STREAM) return
            val payload = sendPayload ?: return
            val end = minOf(sendOffset + 256, payload.size)
            writeBytes(payload.copyOfRange(sendOffset, end))
            sendOffset = end
            if (sendOffset < payload.size) {
                uiHandler.postDelayed(this, 25)
            } else {
                sendState = SendFlow.WAIT_DONE
                rxScan.setLength(0)
                armSendTimeout(30_000)
            }
        }
    }

    private fun scanSendFlow(text: String) {
        rxScan.append(text)
        if (rxScan.length > 512) rxScan.delete(0, rxScan.length - 512)
        when (sendState) {
            SendFlow.LOAD_DRIVER -> {
                if (!rxScan.contains("> ")) return
                rxScan.setLength(0)
                if (sendStep < 6) {
                    sendStep++
                    writeBytes("(load SDW$sendStep.LSP)\n".toByteArray())
                    armSendTimeout(20_000)
                } else {
                    val payload = sendPayload ?: return
                    val codes = sendName83.joinToString(" ")
                    sendState = SendFlow.WAIT_READY
                    writeBytes("(recv-file (quote ($codes)) ${payload.size})\n".toByteArray())
                    armSendTimeout(30_000)
                }
            }
            SendFlow.WAIT_READY -> {
                if (!rxScan.contains("STORE-READY")) return
                rxScan.setLength(0)
                sendState = SendFlow.STREAM
                sendTimeout?.let { uiHandler.removeCallbacks(it) }
                uiHandler.post(streamChunk)
            }
            SendFlow.WAIT_DONE -> {
                if (!rxScan.contains("> ")) return
                val size = sendPayload?.size ?: 0
                sendState = SendFlow.IDLE
                sendTimeout?.let { uiHandler.removeCallbacks(it) }
                runOnUiThread {
                    appendConsole("[sent $sendDisplayName: $size bytes stored on card]\n")
                    setStatus("Sent $sendDisplayName ($size bytes)")
                }
            }
            else -> {}
        }
    }

    override fun onRunError(e: Exception) {
        runOnUiThread {
            appendConsole("\n[serial error: ${e.message}]\n")
            disconnect()
            setStatus("Disconnected (serial error)")
        }
    }

    private fun sendInput() {
        val text = inputField.text.toString()
        if (text.isEmpty()) return
        if (writeBytes((text + "\n").toByteArray())) {
            inputField.text.clear()
        }
    }

    private fun writeBytes(bytes: ByteArray): Boolean {
        val p = port
        if (p == null) {
            setStatus("Not connected")
            return false
        }
        return try {
            p.write(bytes, WRITE_TIMEOUT_MS)
            true
        } catch (e: IOException) {
            setStatus("Write failed: ${e.message}")
            false
        }
    }

    // ---- UI helpers ----

    private fun appendConsole(text: String) {
        val current = consoleText.text.toString()
        var next = current + text
        if (next.length > MAX_CONSOLE_CHARS) {
            next = next.substring(next.length - MAX_CONSOLE_CHARS)
        }
        consoleText.text = next
        consoleScroll.post { consoleScroll.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    private fun setStatus(text: String) {
        statusText.text = text
    }

    @Suppress("DEPRECATION")
    private inline fun <reified T : android.os.Parcelable> Intent.parcelableExtra(name: String): T? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(name, T::class.java)
        } else {
            getParcelableExtra(name) as? T
        }
}

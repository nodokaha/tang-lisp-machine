package org.tanglisp.companion

/**
 * Parser and renderer for TangLisp heap-image world files (.BIN).
 *
 * Mirrors heap_save_to() / heap_restore_from() in lisp-sd/lisp_sd.c:
 *   block 0  header: "TLHP", version, used, nsyms, genv, cksum, payload size
 *   payload  cells (ncells x 8B: car, cdr as u32 LE), then the symbol
 *            table (capacity x 16B names), then usedbits (ncells/8 bytes)
 *   cksum    plain byte sum of the payload
 *
 * val encoding: NIL = 0, int = (n shl 1) or 1, symbol = symtab addr or 2,
 * prim = (index shl 3) or 6, bytes = arena addr or 4, cons = cell addr.
 * The base addresses live in the firmware build, so each known image
 * version maps to a layout profile (bases taken from that build's fw.elf).
 */
class WorldParseException(message: String) : Exception(message)

/** The most recent world fetched live from the board, if any. The
 *  viewer opens on it automatically; a picked file replaces it. */
object WorldInbox {
    @Volatile var latest: ByteArray? = null
    @Volatile var latestName: String = "board (live)"
}

class WorldImage private constructor(
    val version: Int,
    val usedCount: Int,
    val nsyms: Int,
    val genv: Int,
    val checksumOk: Boolean,
    val ncells: Int,
    private val car: IntArray,
    private val cdr: IntArray,
    val symbols: List<String>,
    private val used: BooleanArray,
    private val cellsBase: Int,
    private val symtabBase: Int
) {
    data class Binding(val name: String, val value: Int)

    private val closureSymVal: Int =
        symbols.indexOf("*closure*").let {
            if (it >= 0) symtabBase + it * 16 + 2 else -1
        }

    val reachable: BooleanArray by lazy { computeReachable() }
    val reachableCount: Int get() = reachable.count { it }

    fun isUsed(i: Int): Boolean = used[i]
    fun isReachable(i: Int): Boolean = reachable[i]

    private fun cellIndex(v: Int): Int = (v - cellsBase) / 8
    private fun isCons(v: Int): Boolean =
        v != 0 && (v and 7) == 0 && cellIndex(v) in 0 until ncells

    private fun isClosure(v: Int): Boolean =
        closureSymVal >= 0 && isCons(v) && car[cellIndex(v)] == closureSymVal

    private fun symbolName(v: Int): String? {
        if ((v and 7) != 2) return null
        val idx = (v - 2 - symtabBase) / 16
        return if (idx in symbols.indices && symbols[idx].isNotEmpty())
            symbols[idx] else "#<sym $idx>"
    }

    private fun computeReachable(): BooleanArray {
        val seen = BooleanArray(ncells)
        val stack = ArrayDeque<Int>()
        if (isCons(genv)) stack.addLast(genv)
        var guard = 0
        while (stack.isNotEmpty() && guard++ < ncells * 4) {
            val v = stack.removeLast()
            if (!isCons(v)) continue
            val i = cellIndex(v)
            if (seen[i]) continue
            seen[i] = true
            stack.addLast(car[i])
            stack.addLast(cdr[i])
        }
        return seen
    }

    /** The global environment as (name . value) pairs, in file order. */
    fun bindings(): List<Binding> {
        val out = mutableListOf<Binding>()
        var cur = genv
        var guard = 0
        while (isCons(cur) && guard++ < 4096) {
            val pair = car[cellIndex(cur)]
            if (!isCons(pair)) break
            val pi = cellIndex(pair)
            out += Binding(symbolName(car[pi]) ?: "?", cdr[pi])
            cur = cdr[cellIndex(cur)]
        }
        return out
    }

    /** One-line summary of a value, for the bindings list. */
    fun summarize(v: Int): String = when {
        v == 0 -> "()"
        (v and 1) == 1 -> (v shr 1).toString()
        (v and 7) == 2 -> symbolName(v) ?: "?"
        (v and 7) == 6 -> "#<prim ${primName(v ushr 3)}>"
        (v and 7) == 4 -> "#<bytes>"
        isClosure(v) -> {
            val rest = cdr[cellIndex(v)]
            val params = if (isCons(rest)) render(car[cellIndex(rest)]) else "?"
            "(lambda $params …)"
        }
        isCons(v) -> {
            val parts = mutableListOf<String>()
            var cur = v
            var guard = 0
            while (isCons(cur) && guard++ < 5) {
                parts += summarizeShallow(car[cellIndex(cur)])
                cur = cdr[cellIndex(cur)]
            }
            val tail = when {
                cur == 0 -> ""
                isCons(cur) -> " …"
                else -> " . " + summarizeShallow(cur)
            }
            "(" + parts.joinToString(" ") + tail + ")"
        }
        else -> "#<???>"
    }

    private fun summarizeShallow(v: Int): String = when {
        v == 0 -> "()"
        (v and 1) == 1 -> (v shr 1).toString()
        (v and 7) == 2 -> symbolName(v) ?: "?"
        (v and 7) == 6 -> primName(v ushr 3)
        isClosure(v) -> "#<closure>"
        isCons(v) -> "(…)"
        else -> "#<bytes>"
    }

    /** Full s-expression rendering, depth- and size-limited. The env of a
     *  closure is not expanded (it is circular by construction). */
    fun render(v: Int): String {
        budget = 600
        return renderRec(v, 0)
    }

    private var budget = 0

    private fun renderRec(v: Int, depth: Int): String {
        if (--budget < 0 || depth > 12) return "…"
        return when {
            v == 0 -> "()"
            (v and 1) == 1 -> (v shr 1).toString()
            (v and 7) == 2 -> symbolName(v) ?: "?"
            (v and 7) == 6 -> "#<prim ${primName(v ushr 3)}>"
            (v and 7) == 4 -> "#<bytes>"
            isClosure(v) -> {
                // (*closure* params body env): show as a lambda form.
                var rest = cdr[cellIndex(v)]
                val params = if (isCons(rest)) car[cellIndex(rest)] else 0
                rest = if (isCons(rest)) cdr[cellIndex(rest)] else 0
                val body = if (isCons(rest)) car[cellIndex(rest)] else 0
                val forms = mutableListOf<String>()
                var cur = body
                var guard = 0
                while (isCons(cur) && guard++ < 16) {
                    forms += renderRec(car[cellIndex(cur)], depth + 1)
                    cur = cdr[cellIndex(cur)]
                }
                "(lambda " + renderRec(params, depth + 1) +
                    (if (forms.isEmpty()) "" else " " + forms.joinToString(" ")) + ")"
            }
            isCons(v) -> {
                val parts = mutableListOf<String>()
                var cur = v
                var guard = 0
                while (isCons(cur) && guard++ < 64) {
                    parts += renderRec(car[cellIndex(cur)], depth + 1)
                    cur = cdr[cellIndex(cur)]
                }
                if (cur != 0) parts += ". " + renderRec(cur, depth + 1)
                "(" + parts.joinToString(" ") + ")"
            }
            else -> "#<???>"
        }
    }

    companion object {
        private data class Profile(
            val ncells: Int, val symCap: Int,
            val cellsBase: Int, val symtabBase: Int
        )

        // Layout profiles per IMG_VERSION, bases from each build's
        // fw.elf symbol table. v7: PROG39 (NCELLS 320). v8: PROG40
        // with the (dump) prim (NCELLS 288, for the stack margin).
        private val PROFILES = mapOf(
            7 to Profile(320, 80, 0x6C60, 0x5560),
            8 to Profile(288, 80, 0x6D20, 0x5620),
            12 to Profile(2560, 192, 0x8450, 0x6850)
        )

        private val PRIM_NAMES = listOf(
            "+", "-", "*", "=", "<", ">", "cons", "car", "cdr",
            "null?", "pair?", "eq?", "not", "list", "print", "save", "load",
            "make-bytes", "bytes-ref", "bytes-set!", "bytes-length", "bytes?",
            "peek", "poke", "spi-cs", "spi-fast", "spi-byte", "ash",
            "logand", "logior", "keys", "enc", "restore", "dir", "delete-file",
            "dump"
        )

        fun primName(idx: Int): String =
            PRIM_NAMES.getOrNull(idx) ?: idx.toString()

        private fun u32(b: ByteArray, off: Int): Int =
            (b[off].toInt() and 0xFF) or
                ((b[off + 1].toInt() and 0xFF) shl 8) or
                ((b[off + 2].toInt() and 0xFF) shl 16) or
                ((b[off + 3].toInt() and 0xFF) shl 24)

        fun parse(bytes: ByteArray): WorldImage {
            if (bytes.size < 512)
                throw WorldParseException("file is too small to be a world")
            if (bytes[0] != 'T'.code.toByte() || bytes[1] != 'L'.code.toByte() ||
                bytes[2] != 'H'.code.toByte() || bytes[3] != 'P'.code.toByte()
            ) throw WorldParseException("not a TangLisp world (bad magic)")

            val version = u32(bytes, 4)
            val profile = PROFILES[version]
                ?: throw WorldParseException(
                    "world version $version is not known to this app yet")
            val usedCount = u32(bytes, 8)
            val nsyms = u32(bytes, 12)
            val genv = u32(bytes, 16)
            val cksum = u32(bytes, 20)
            val payloadSize = u32(bytes, 24)
            val expected = profile.ncells * 8 + profile.symCap * 16 +
                profile.ncells / 8
            if (payloadSize != expected)
                throw WorldParseException(
                    "payload size $payloadSize does not match version " +
                        "$version layout ($expected)")
            if (bytes.size < 512 + payloadSize)
                throw WorldParseException("file is truncated")

            var sum = 0
            for (i in 0 until payloadSize) sum += bytes[512 + i].toInt() and 0xFF
            val checksumOk = sum == cksum

            val car = IntArray(profile.ncells)
            val cdr = IntArray(profile.ncells)
            for (i in 0 until profile.ncells) {
                car[i] = u32(bytes, 512 + i * 8)
                cdr[i] = u32(bytes, 512 + i * 8 + 4)
            }
            val symOff = 512 + profile.ncells * 8
            val symbols = (0 until profile.symCap).map { i ->
                val raw = bytes.copyOfRange(symOff + i * 16, symOff + i * 16 + 16)
                val end = raw.indexOf(0).let { if (it < 0) 16 else it }
                String(raw, 0, end, Charsets.US_ASCII)
            }
            val bitsOff = symOff + profile.symCap * 16
            val used = BooleanArray(profile.ncells) { i ->
                ((bytes[bitsOff + i / 8].toInt() and 0xFF) shr (i % 8)) and 1 == 1
            }
            return WorldImage(
                version, usedCount, nsyms, genv, checksumOk,
                profile.ncells, car, cdr, symbols, used,
                profile.cellsBase, profile.symtabBase
            )
        }
    }
}

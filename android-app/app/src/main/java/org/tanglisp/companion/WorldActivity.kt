package org.tanglisp.companion

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * World viewer: opens a TangLisp heap image (.BIN, written by (save …)
 * on the board) and draws it — a lamplit heap grid, the global
 * environment's bindings, and a full rendering of any binding's value.
 */
class WorldActivity : Activity() {

    private lateinit var infoText: TextView
    private lateinit var detailText: TextView
    private lateinit var grid: HeapGridView
    private lateinit var bindingsBox: LinearLayout
    private var selectedRow: TextView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_world)
        infoText = findViewById(R.id.worldInfo)
        detailText = findViewById(R.id.worldDetail)
        grid = findViewById(R.id.heapGrid)
        bindingsBox = findViewById(R.id.bindingsBox)
        findViewById<Button>(R.id.openWorldButton).setOnClickListener {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
            }
            @Suppress("DEPRECATION")
            startActivityForResult(intent, REQ_OPEN)
        }
        // A world fetched live from the board opens on its own.
        WorldInbox.latest?.let { bytes ->
            try {
                show(WorldImage.parse(bytes), WorldInbox.latestName)
            } catch (e: Exception) {
                infoText.text = "The fetched world would not parse: ${e.message}"
            }
        }
    }

    @Deprecated("framework-only picker flow")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_OPEN || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            val bytes = contentResolver.openInputStream(uri)?.readBytes()
                ?: throw WorldParseException("could not open the file")
            show(WorldImage.parse(bytes), displayName(uri))
        } catch (e: Exception) {
            infoText.text = "That file would not open as a world: ${e.message}"
        }
    }

    private fun displayName(uri: Uri): String {
        try {
            contentResolver.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && c.moveToFirst()) return c.getString(idx)
            }
        } catch (_: Exception) {
        }
        return uri.lastPathSegment ?: "world"
    }

    private fun show(image: WorldImage, name: String) {
        val ck = if (image.checksumOk) "checksum OK" else "checksum MISMATCH"
        infoText.text = "$name — world v${image.version}\n" +
            "cells ${image.usedCount}/${image.ncells} used · " +
            "${image.reachableCount} alive in the global env · " +
            "symbols ${image.nsyms} · $ck"
        grid.image = image

        bindingsBox.removeAllViews()
        selectedRow = null
        val bindings = image.bindings()
        if (bindings.isEmpty()) {
            detailText.text = "This world has no global bindings."
            return
        }
        for (b in bindings) {
            val row = TextView(this).apply {
                text = "${b.name}  →  ${image.summarize(b.value)}"
                setTextColor(getColor(R.color.text_cream))
                textSize = 13f
                typeface = android.graphics.Typeface.MONOSPACE
                setPadding(10, 10, 10, 10)
                setOnClickListener {
                    selectedRow?.background = null
                    background = getDrawable(R.drawable.console_bg)
                    selectedRow = this
                    detailText.text = "${b.name}\n${image.render(b.value)}"
                }
            }
            bindingsBox.addView(row)
        }
        // Open on the first binding so the detail box is never empty.
        (bindingsBox.getChildAt(0) as? TextView)?.callOnClick()
    }

    companion object {
        private const val REQ_OPEN = 42
    }
}

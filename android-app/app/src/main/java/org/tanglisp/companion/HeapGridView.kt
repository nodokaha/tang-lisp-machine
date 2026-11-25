package org.tanglisp.companion

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View

/**
 * The world's heap as a grid of lamplit cells: amber cells are alive
 * (reachable from the global environment), blue-grey cells are used
 * but no longer reachable, dark cells are free.
 */
class HeapGridView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    var image: WorldImage? = null
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

    private fun cellCount(): Int = image?.ncells ?: 320

    // Column count adapts to the world size so the grid's height
    // stays near 0.62 x width. A fixed 20 columns was fine for the
    // 288-cell worlds (15 rows), but a 2560-cell world needs 128
    // rows at 20 columns — over 2000dp tall, which pushed the
    // detail box and the whole bindings list off-screen.
    private fun cols(): Int =
        maxOf(20, kotlin.math.ceil(kotlin.math.sqrt(cellCount() / 0.62)).toInt())

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val width = MeasureSpec.getSize(widthMeasureSpec)
        val cols = cols()
        val rows = (cellCount() + cols - 1) / cols
        setMeasuredDimension(width, (width / cols) * rows)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val img = image
        val n = cellCount()
        val cols = cols()
        val cell = width.toFloat() / cols
        val gap = cell * 0.14f
        val radius = cell * 0.22f
        for (i in 0 until n) {
            val x = (i % cols) * cell
            val y = (i / cols) * cell
            paint.color = when {
                img != null && img.isReachable(i) -> 0xFFD98E4A.toInt()
                img != null && img.isUsed(i) -> 0xFF54687E.toInt()
                else -> 0xFF20261F.toInt()
            }
            canvas.drawRoundRect(
                x + gap / 2, y + gap / 2,
                x + cell - gap / 2, y + cell - gap / 2,
                radius, radius, paint
            )
        }
    }
}

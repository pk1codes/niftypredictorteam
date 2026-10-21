package com.pk1codes.niftyboard

import android.content.Intent
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.max
import kotlin.math.min

private val Paper = Color(0xFFF3EEE7)
private val Ink = Color(0xFF1C1915)
private val Mute = Color(0xFF746C62)
private val Card = Color(0xFFFFFCF8)
private val Band = Color(0xFF6B3FA0)
private val Spot = Color(0xFF0C7A3A)
private val Gift = Color(0xFFC47B12)
private val Line = Color(0xFFE6DFD4)

@Composable
fun BoardScreen(forecast: Forecast?, marks: Marks) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Text(
            "NIFTY BOARD",
            color = Mute,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 2.2.sp,
        )
        Spacer(Modifier.height(14.dp))
        if (forecast == null) {
            WaitingCard()
        } else {
            RangeCard(forecast, marks)
            Spacer(Modifier.height(14.dp))
            WhyCard(forecast)
        }
    }
}

@Composable
private fun RangeCard(forecast: Forecast, marks: Marks) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(10.dp, RoundedCornerShape(28.dp), ambientColor = Color(0x14000000))
            .clip(RoundedCornerShape(28.dp))
            .background(Card)
            .padding(top = 0.dp),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(5.dp)
                .background(Band),
        )
        Column(Modifier.padding(start = 22.dp, end = 22.dp, top = 18.dp, bottom = 20.dp)) {
            Text(
                "NEXT 24H CLOSE",
                color = Mute,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 1.4.sp,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "${forecast.lowText}  –  ${forecast.highText}",
                color = Ink,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Medium,
                fontSize = 32.sp,
                lineHeight = 36.sp,
                letterSpacing = (-0.6).sp,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                "${forecast.dueLabel}, ${forecast.gap}.",
                color = Mute,
                fontSize = 15.sp,
                lineHeight = 20.sp,
            )
            Spacer(Modifier.height(8.dp))
            RangeTrack(forecast, marks.nifty, marks.gift)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                QuoteTile(marks.nifty, Spot, Modifier.weight(1f))
                QuoteTile(marks.gift, Gift, Modifier.weight(1f))
            }
            Spacer(Modifier.height(14.dp))
            Text(
                "The shade is the quoted band. Green is Nifty. Amber is GIFT. They move while that market is live.",
                color = Mute,
                fontSize = 13.sp,
                lineHeight = 18.sp,
            )
        }
    }
}

@Composable
private fun RangeTrack(forecast: Forecast, nifty: Quote, gift: Quote) {
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(168.dp),
    ) {
        val pad = 28.dp.toPx()
        val cushion = max(forecast.sigma * 0.25, 8.0)
        val points = mutableListOf(forecast.low, forecast.high)
        nifty.price?.let { points += it }
        gift.price?.let { points += it }
        val lo = points.minOrNull()!! - cushion
        val hi = points.maxOrNull()!! + cushion
        val span = (hi - lo).takeIf { it != 0.0 } ?: 1.0
        fun sx(value: Double): Float = pad + ((value - lo) / span * (size.width - 2 * pad)).toFloat()

        val x0 = sx(forecast.low)
        val x1 = sx(forecast.high)
        val xa = sx(forecast.anchor)
        val trackTop = 96.dp.toPx()
        val trackHeight = 22.dp.toPx()

        drawRoundRect(
            color = Band.copy(alpha = 0.20f),
            topLeft = Offset(min(x0, x1), trackTop),
            size = Size(kotlin.math.abs(x1 - x0).coerceAtLeast(2f), trackHeight),
            cornerRadius = CornerRadius(8.dp.toPx(), 8.dp.toPx()),
        )
        drawLine(
            color = Ink,
            start = Offset(xa, trackTop - 16.dp.toPx()),
            end = Offset(xa, trackTop + trackHeight + 16.dp.toPx()),
            strokeWidth = 2.dp.toPx(),
        )
        val label = textPaint(13.sp.toPx(), Mute.toArgb(), bold = true)
        val quiet = textPaint(11.sp.toPx(), Mute.toArgb(), bold = false)
        drawContext.canvas.nativeCanvas.drawText(forecast.lowText, x0, 22.dp.toPx(), label)
        drawContext.canvas.nativeCanvas.drawText(forecast.highText, x1, 22.dp.toPx(), label)
        drawContext.canvas.nativeCanvas.drawText("Last close", xa, 58.dp.toPx(), quiet)

        fun dot(price: Double?, color: Color, above: Boolean) {
            if (price == null) return
            val cx = sx(price).coerceIn(pad, size.width - pad)
            val cy = if (above) trackTop - 14.dp.toPx() else trackTop + trackHeight + 14.dp.toPx()
            drawCircle(color = Color.White, radius = 8.dp.toPx(), center = Offset(cx, cy))
            drawCircle(color = color, radius = 6.dp.toPx(), center = Offset(cx, cy))
        }
        dot(nifty.price, Spot, above = true)
        dot(gift.price, Gift, above = false)
    }
}

private fun textPaint(size: Float, color: Int, bold: Boolean): Paint =
    Paint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = color
        textSize = size
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create(Typeface.SANS_SERIF, if (bold) Typeface.BOLD else Typeface.NORMAL)
    }

@Composable
private fun QuoteTile(quote: Quote, color: Color, modifier: Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(Paper)
            .padding(horizontal = 12.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(9.dp)
                    .clip(CircleShape)
                    .background(color),
            )
            Spacer(Modifier.width(6.dp))
            Text(quote.name, color = Mute, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.weight(1f))
            LiveMark(quote.live)
        }
        Spacer(Modifier.height(6.dp))
        Text(
            quote.priceText,
            color = Ink,
            fontFamily = FontFamily.Serif,
            fontSize = 26.sp,
            fontWeight = FontWeight.Medium,
        )
        val whenText = when {
            quote.price == null -> "Waiting for a print"
            quote.clock.isBlank() -> if (quote.live) "Live" else "Last print"
            quote.live -> "Live · ${quote.clock}"
            else -> "Closed · ${quote.clock}"
        }
        Text(whenText, color = if (quote.live) Spot else Mute, fontSize = 12.sp)
    }
}

@Composable
private fun LiveMark(live: Boolean) {
    if (!live) {
        Text("CLOSED", color = Mute, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp)
        return
    }
    val pulse = rememberInfiniteTransition(label = "live")
    val alpha by pulse.animateFloat(
        initialValue = 0.35f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "alpha",
    )
    Text("LIVE", color = Spot.copy(alpha = alpha), fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp)
}

@Composable
private fun WhyCard(forecast: Forecast) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(28.dp))
            .background(Card)
            .padding(22.dp),
    ) {
        Text(
            "WHY THIS RANGE",
            color = Mute,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(10.dp))
        ProofLine(forecast.coverage)
        ProofLine(forecast.center)
        ProofLine(forecast.record)
        if (forecast.signedLine.isNotBlank()) ProofLine(forecast.signedLine)
        Spacer(Modifier.height(8.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Spacer(Modifier.height(10.dp))
        Text(
            "This is a probability, not a promise.",
            color = Mute,
            fontSize = 13.sp,
        )
        val context = LocalContext.current
        Text(
            "Privacy",
            color = Band,
            fontSize = 13.sp,
            modifier = Modifier.clickable {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://pk1codes.github.io/niftypredictorteam/privacy.html"))
                )
            },
        )
    }
}

@Composable
private fun ProofLine(text: String) {
    if (text.isBlank()) return
    Text(text, color = Ink, fontSize = 15.sp, lineHeight = 21.sp)
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun WaitingCard() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(28.dp))
            .background(Card)
            .padding(22.dp),
    ) {
        Text(
            "The signed range is not on this phone yet.",
            color = Ink,
            fontFamily = FontFamily.Serif,
            fontSize = 28.sp,
            lineHeight = 34.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "It appears after the next refresh, once the signed call is published.",
            color = Mute,
            fontSize = 15.sp,
            lineHeight = 21.sp,
        )
    }
}

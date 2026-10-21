package com.pk1codes.niftyboard

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs

private const val FORECAST_URL =
    "https://raw.githubusercontent.com/pk1codes/niftypredictorteam/main/docs/forecast.json"
private const val NIFTY_URL =
    "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1m&range=1d"
private const val GIFT_URL = "https://www.nseix.com/api/market-rate?type=derivatives"
private const val LIVE_SECONDS = 300L
private val IST: ZoneId = ZoneId.of("Asia/Kolkata")
private val GIFT_TIME: DateTimeFormatter =
    DateTimeFormatter.ofPattern("dd-MMM-yyyy HH:mm:ss", Locale.US)
private val CLOCK: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm", Locale.US)

data class Forecast(
    val lowText: String,
    val highText: String,
    val anchor: Double,
    val sigma: Double,
    val low: Double,
    val high: Double,
    val dueLabel: String,
    val gap: String,
    val coverage: String,
    val center: String,
    val record: String,
    val signedLine: String,
)

data class Quote(
    val name: String,
    val price: Double?,
    val priceText: String,
    val live: Boolean,
    val clock: String,
)

data class Marks(val nifty: Quote, val gift: Quote)

fun emptyMarks(): Marks = Marks(
    Quote("Nifty", null, "—", false, ""),
    Quote("GIFT", null, "—", false, ""),
)

fun loadForecast(context: Context): Forecast? {
    val fresh = runCatching { readUrl(FORECAST_URL) }.getOrNull()
    if (fresh != null) {
        parseForecast(fresh)?.let { parsed ->
            context.filesDir.resolve("forecast.json").writeText(fresh)
            return parsed
        }
    }
    val cached = context.filesDir.resolve("forecast.json")
    if (cached.exists()) {
        parseForecast(cached.readText())?.let { return it }
    }
    val asset = context.assets.open("forecast.json").bufferedReader().use { it.readText() }
    return parseForecast(asset)
}

fun loadMarks(): Marks {
    val now = ZonedDateTime.now(IST)
    val nifty = runCatching { niftyQuote(now) }.getOrDefault(Quote("Nifty", null, "—", false, ""))
    val gift = runCatching { giftQuote(now) }.getOrDefault(Quote("GIFT", null, "—", false, ""))
    return Marks(nifty, gift)
}

private fun niftyQuote(now: ZonedDateTime): Quote {
    val root = JSONObject(readUrl(NIFTY_URL, "niftyboard/1.0"))
    val meta = root.getJSONObject("chart").getJSONArray("result").getJSONObject(0).getJSONObject("meta")
    if (!meta.has("regularMarketPrice")) return Quote("Nifty", null, "—", false, "")
    val price = meta.getDouble("regularMarketPrice")
    val stamp = if (meta.has("regularMarketTime") && !meta.isNull("regularMarketTime")) {
        epochStamp(meta.getLong("regularMarketTime"))
    } else {
        null
    }
    return quote("Nifty", price, stamp, now)
}

private fun giftQuote(now: ZonedDateTime): Quote {
    val root = JSONObject(readUrl(GIFT_URL, "Mozilla/5.0 niftyboard/1.0"))
    val rows = root.optJSONArray("data") ?: return Quote("GIFT", null, "—", false, "")
    var seen = linkedSetOf<String>()
    var near: JSONObject? = null
    for (index in 0 until rows.length()) {
        val row = rows.optJSONObject(index) ?: continue
        if (row.optString("SYMBOL") != "NIFTY" || row.optString("INSTRUMENTTYPE") != "FUTIDX") continue
        val expiry = row.optString("EXPIRYDATE")
        if (expiry.isBlank() || !seen.add(expiry)) continue
        near = row
        break
    }
    val chosen = near ?: return Quote("GIFT", null, "—", false, "")
    val price = chosen.optString("LASTPRICE").replace(",", "").toDoubleOrNull()
        ?: return Quote("GIFT", null, "—", false, "")
    val stamp = chosen.optString("TIMESTMP").takeIf { it.isNotBlank() }?.let {
        runCatching { ZonedDateTime.of(java.time.LocalDateTime.parse(it, GIFT_TIME), IST) }.getOrNull()
    }
    return quote("GIFT", price, stamp, now)
}

private fun quote(name: String, price: Double, stamp: ZonedDateTime?, now: ZonedDateTime): Quote {
    val live = stamp != null && abs(Duration.between(stamp, now).seconds) <= LIVE_SECONDS
    val clock = stamp?.format(CLOCK).orEmpty()
    return Quote(name, price, formatPoints(price), live, clock)
}

private fun epochStamp(raw: Long): ZonedDateTime {
    val seconds = if (raw > 10_000_000_000L) raw / 1000 else raw
    return Instant.ofEpochSecond(seconds).atZone(IST)
}

private fun parseForecast(raw: String): Forecast? {
    val json = JSONObject(raw)
    if (!json.optBoolean("ready", false) || !json.has("sigma")) return null
    val sigma = json.getDouble("sigma")
    val anchor = json.getDouble("anchor")
    if (sigma == 0.0) return null
    return Forecast(
        lowText = json.optString("low_text", formatPoints(anchor - sigma)),
        highText = json.optString("high_text", formatPoints(anchor + sigma)),
        anchor = anchor,
        sigma = sigma,
        low = json.optDouble("low", anchor - sigma),
        high = json.optDouble("high", anchor + sigma),
        dueLabel = json.optString("due_label", "Next cash close"),
        gap = json.optString("gap", "the next cash close"),
        coverage = json.optString("coverage"),
        center = json.optString("center"),
        record = json.optString("record"),
        signedLine = json.optString("signed_line"),
    )
}

private fun formatPoints(value: Double): String =
    String.format(Locale.US, "%,.0f", value)

private fun readUrl(url: String, agent: String = "niftyboard/1.0"): String {
    val connection = URL(url).openConnection() as HttpURLConnection
    connection.connectTimeout = 12_000
    connection.readTimeout = 12_000
    connection.setRequestProperty("User-Agent", agent)
    connection.setRequestProperty("Accept", "application/json")
    connection.inputStream.bufferedReader().use { reader ->
        val body = reader.readText()
        if (connection.responseCode !in 200..299) error("HTTP ${connection.responseCode}")
        return body
    }
}

package com.pk1codes.niftyboard

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.InstallStateUpdatedListener
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.InstallStatus
import com.google.android.play.core.install.model.UpdateAvailability
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = true
        checkForUpdate()
        setContent {
            var forecast by remember { mutableStateOf<Forecast?>(null) }
            var marks by remember { mutableStateOf(emptyMarks()) }
            LaunchedEffect(Unit) {
                var lap = 0
                while (isActive) {
                    if (lap % 40 == 0) {
                        val next = withContext(Dispatchers.IO) { loadForecast(this@MainActivity) }
                        if (next != null) forecast = next
                    }
                    marks = withContext(Dispatchers.IO) { loadMarks() }
                    lap += 1
                    delay(15_000)
                }
            }
            BoardScreen(forecast, marks)
        }
    }

    private fun checkForUpdate() {
        val manager = AppUpdateManagerFactory.create(this)
        val listener = InstallStateUpdatedListener { state ->
            if (state.installStatus() == InstallStatus.DOWNLOADED) manager.completeUpdate()
        }
        manager.registerListener(listener)
        manager.appUpdateInfo.addOnSuccessListener { info ->
            val ready = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
                info.isUpdateTypeAllowed(AppUpdateType.FLEXIBLE)
            if (ready) {
                manager.startUpdateFlowForResult(
                    info,
                    this,
                    AppUpdateOptions.newBuilder(AppUpdateType.FLEXIBLE).build(),
                    41,
                )
            }
            if (info.installStatus() == InstallStatus.DOWNLOADED) manager.completeUpdate()
        }
    }
}

package pe.empresa.banca.login

import android.content.Context
import android.os.Bundle
import android.util.Log
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.net.ssl.X509TrustManager

const val API_KEY = "sk_live_51HfQ2x9Kd"
const val URL_BASE = "http://api.empresa.pe/v1"

class LoginActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.addJavascriptInterface(Puente(), "Android")
    }

    fun guardarSesion(token: String) {
        val prefs = getSharedPreferences("sesion", Context.MODE_PRIVATE)
        prefs.edit().putString("access_token", token).apply()
        Log.d("Login", "Token recibido: $token")
    }

    fun huella(clave: String): ByteArray = MessageDigest.getInstance("MD5").digest(clave.toByteArray())
}

class ConfiarEnTodo : X509TrustManager {
    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}

class Puente

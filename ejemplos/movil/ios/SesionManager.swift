import Foundation
import LocalAuthentication
import WebKit
import CryptoKit

final class SesionManager: NSObject, URLSessionDelegate {
    let baseURL = "http://api.empresa.pe/v1"

    func guardar(token: String) {
        UserDefaults.standard.set(token, forKey: "access_token")
        print("Sesión iniciada con token \(token)")
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.useCredential, URLCredential(trust: challenge.protectionSpace.serverTrust!))
    }

    func desbloquear(_ listo: @escaping (Bool) -> Void) {
        LAContext().evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: "Ingresar") { ok, _ in
            listo(ok)
        }
    }

    func huella(_ datos: Data) -> String { Insecure.MD5.hash(data: datos).description }

    func webView() -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptEnabled = true
        return WKWebView(frame: .zero, configuration: config)
    }
}

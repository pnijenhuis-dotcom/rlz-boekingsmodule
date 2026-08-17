// VeiligeOpslag — dunne eigen Capacitor-plugin rond de iOS Keychain (store-app fase 4).
// Bewaart het refresh-token van de apparaat-gebonden sessie (verkenning/17 (d) route 2):
// de SameSite-cookie werkt niet in de webview, localStorage is voor een token onacceptabel —
// Keychain is de juiste plek. Zelfde geen-community-pakket-lijn als NatievePasskey (auth-kern).
//
// kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: token nooit in iCloud-backups/sync en
// pas leesbaar ná de eerste unlock — past bij een achtergrond-loze app.
// VERIFICATIESTATUS: compileert pas met de volledige Xcode — bewijs = kliktest-blok fase 4.

import Foundation
import Capacitor
import Security

@objc(VeiligeOpslagPlugin)
public class VeiligeOpslagPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "VeiligeOpslagPlugin"
    public let jsName = "VeiligeOpslag"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "zet", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "haal", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "verwijder", returnType: CAPPluginReturnPromise)
    ]

    private let service = Bundle.main.bundleIdentifier ?? "nl.aknijenhuis.goedkeuren"

    private func basisQuery(_ sleutel: String) -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: sleutel
        ]
    }

    @objc func zet(_ call: CAPPluginCall) {
        guard let sleutel = call.getString("sleutel"), let waarde = call.getString("waarde") else {
            call.reject("sleutel/waarde ontbreekt")
            return
        }
        let data = Data(waarde.utf8)
        var query = basisQuery(sleutel)
        // Upsert: eerst updaten, bestaat de rij niet dan toevoegen.
        let update: [String: Any] = [kSecValueData as String: data]
        var status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            query[kSecValueData as String] = data
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(query as CFDictionary, nil)
        }
        if status == errSecSuccess {
            call.resolve()
        } else {
            call.reject("Keychain-schrijffout (\(status))")
        }
    }

    @objc func haal(_ call: CAPPluginCall) {
        guard let sleutel = call.getString("sleutel") else {
            call.reject("sleutel ontbreekt")
            return
        }
        var query = basisQuery(sleutel)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var resultaat: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &resultaat)
        if status == errSecSuccess, let data = resultaat as? Data, let waarde = String(data: data, encoding: .utf8) {
            call.resolve(["waarde": waarde])
        } else if status == errSecItemNotFound {
            call.resolve(["waarde": NSNull()])
        } else {
            call.reject("Keychain-leesfout (\(status))")
        }
    }

    @objc func verwijder(_ call: CAPPluginCall) {
        guard let sleutel = call.getString("sleutel") else {
            call.reject("sleutel ontbreekt")
            return
        }
        let status = SecItemDelete(basisQuery(sleutel) as CFDictionary)
        if status == errSecSuccess || status == errSecItemNotFound {
            call.resolve()
        } else {
            call.reject("Keychain-verwijderfout (\(status))")
        }
    }
}

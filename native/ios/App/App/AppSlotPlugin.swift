// AppSlot — dunne eigen Capacitor-plugin voor de biometrie-gemakslaag van het app-lock
// (besluit Peter 31-08, mockup app-lock-pincode.html). Bewaart een KOPIE van het lokale
// anker (de sleutel waarmee de webcode het refresh-token versleutelt) achter de
// biometrie-poort van de Keychain; de 5-cijferige code blijft het altijd-werkende pad en
// leeft volledig in de webcode (PBKDF2-wrap in VeiligeOpslag).
//
// HARDE EIS (mockup-notitie ②): SecAccessControl mét .biometryAny, expliciet NIET
// .biometryCurrentSet — een nieuw ingeschreven gezicht of biometrie-falen mag de kopie nooit
// onbruikbaar maken; kSecAttrAccessibleWhenUnlockedThisDeviceOnly = nooit in iCloud-backups.
// Zelfde geen-community-pakket-lijn als NatievePasskey/VeiligeOpslag (auth-kern).
// VERIFICATIESTATUS: compileert pas met de volledige Xcode — bewijs = kliktest-blok app-lock.

import Foundation
import Capacitor
import LocalAuthentication
import UIKit
import UserNotifications
import Security

@objc(AppSlotPlugin)
public class AppSlotPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppSlotPlugin"
    public let jsName = "AppSlot"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "beschikbaar", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "zetSleutel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "haalSleutel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "wisSleutel", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "zetBadge", returnType: CAPPluginReturnPromise)
    ]

    // Badge-count op het app-icoon (best-practice-punt D4, 01-09): de webcode zet het aantal
    // openstaande accorderingen bij openen en ná elk besluit; de push-payload draagt hetzelfde
    // aantal (aps.badge). Fail-stil: een badge is gemak, nooit een blokkade.
    @objc func zetBadge(_ call: CAPPluginCall) {
        let aantal = max(0, call.getInt("aantal") ?? 0)
        DispatchQueue.main.async {
            if #available(iOS 16.0, *) {
                UNUserNotificationCenter.current().setBadgeCount(aantal) { _ in call.resolve() }
            } else {
                UIApplication.shared.applicationIconBadgeNumber = aantal
                call.resolve()
            }
        }
    }

    private let service = Bundle.main.bundleIdentifier ?? "nl.aknijenhuis.goedkeuren"
    private let account = "appslot_biometrie_sleutel"

    private func basisQuery() -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }

    @objc func beschikbaar(_ call: CAPPluginCall) {
        let context = LAContext()
        var fout: NSError?
        let kan = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &fout)
        let soort: String
        switch context.biometryType {
        case .faceID: soort = "gezicht"
        case .touchID: soort = "vinger"
        default: soort = "geen"
        }
        call.resolve(["beschikbaar": kan, "soort": soort])
    }

    @objc func zetSleutel(_ call: CAPPluginCall) {
        guard let waarde = call.getString("waarde") else {
            call.reject("waarde ontbreekt")
            return
        }
        // Vervangen = eerst weg (een ACL-item is niet updatebaar zonder auth).
        SecItemDelete(basisQuery() as CFDictionary)
        var aclFout: Unmanaged<CFError>?
        guard let acl = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            .biometryAny,  // bewust NIET .biometryCurrentSet (harde eis: her-inschrijving sluit nooit uit)
            &aclFout
        ) else {
            call.reject("Keychain-ACL kon niet worden gemaakt")
            return
        }
        var query = basisQuery()
        query[kSecValueData as String] = Data(waarde.utf8)
        query[kSecAttrAccessControl as String] = acl
        let status = SecItemAdd(query as CFDictionary, nil)
        if status == errSecSuccess {
            call.resolve()
        } else {
            call.reject("Keychain-schrijffout (\(status))")
        }
    }

    @objc func haalSleutel(_ call: CAPPluginCall) {
        let reden = call.getString("reden") ?? "Ontgrendel de app"
        var query = basisQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        let context = LAContext()
        // Geen OS-terugvalknop in de prompt: de code-terugval is ons eigen scherm (mockup 5).
        context.localizedFallbackTitle = ""
        query[kSecUseAuthenticationContext as String] = context
        query[kSecUseOperationPrompt as String] = reden
        // SecItemCopyMatching blokkeert tot de biometrie-prompt is afgerond — nooit op de
        // main thread (de webview zou bevriezen achter de systeem-sheet).
        DispatchQueue.global(qos: .userInitiated).async {
            var resultaat: AnyObject?
            let status = SecItemCopyMatching(query as CFDictionary, &resultaat)
            DispatchQueue.main.async {
                switch status {
                case errSecSuccess:
                    if let data = resultaat as? Data, let waarde = String(data: data, encoding: .utf8) {
                        call.resolve(["waarde": waarde])
                    } else {
                        call.resolve(["waarde": NSNull()])
                    }
                case errSecItemNotFound:
                    call.resolve(["waarde": NSNull()])
                case errSecUserCanceled:
                    call.reject("geannuleerd")
                default:
                    call.reject("mislukt (\(status))")
                }
            }
        }
    }

    @objc func wisSleutel(_ call: CAPPluginCall) {
        let status = SecItemDelete(basisQuery() as CFDictionary)
        if status == errSecSuccess || status == errSecItemNotFound {
            call.resolve()
        } else {
            call.reject("Keychain-verwijderfout (\(status))")
        }
    }
}

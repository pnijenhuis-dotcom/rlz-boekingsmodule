// NatievePasskey — dunne eigen Capacitor-plugin rond de iOS-passkey-API's
// (ASAuthorizationController), native store-app fase 2 (GO Peter 2026-08-16).
//
// Waarom eigen en dun (verkenning/17 beslispunt a): geen supply-chain-afhankelijkheid op een
// klein community-pakket in de auth-kern. Contract met de webcode
// (frontend/src/accordeur/nativePasskey.ts): opties komen binnen als de byte-exacte
// py_webauthn-options-JSON (base64url), het resultaat gaat terug als de WebAuthn-
// credential-JSON in exact de vorm die de backend verwacht — identiek aan wat
// webauthnClient.ts op het webpad uit navigator.credentials bouwt.
//
// rp_id blijft de apex (besluit 0022) — bestaande passkeys blijven geldig. Voorwaarde op
// het toestel: Associated Domains-entitlement (webcredentials:) + apple-app-site-association
// op de apex; zonder die keten weigert iOS de prompt. VERIFICATIESTATUS: dit bestand
// compileert pas met de volledige Xcode (lokaal alleen CLT) — bewijs = kliktest-blok fase 2.

import Foundation
import Capacitor
import AuthenticationServices

private func base64urlNaarData(_ s: String) -> Data? {
    var b64 = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    let rest = b64.count % 4
    if rest > 0 { b64 += String(repeating: "=", count: 4 - rest) }
    return Data(base64Encoded: b64)
}

private func dataNaarBase64url(_ d: Data) -> String {
    return d.base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

@objc(NatievePasskeyPlugin)
public class NatievePasskeyPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NatievePasskeyPlugin"
    public let jsName = "NatievePasskey"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "registreer", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "onderteken", returnType: CAPPluginReturnPromise)
    ]

    // Sessie vasthouden zolang de OS-prompt loopt (delegate mag niet vrijgegeven worden);
    // één prompt tegelijk — een tweede aanroep tijdens een open prompt wordt geweigerd.
    private var lopendeSessie: PasskeySessie?

    @objc func registreer(_ call: CAPPluginCall) {
        start(call, registratie: true)
    }

    @objc func onderteken(_ call: CAPPluginCall) {
        start(call, registratie: false)
    }

    private func start(_ call: CAPPluginCall, registratie: Bool) {
        guard #available(iOS 16.0, *) else {
            call.reject("Passkeys vereisen iOS 16 of nieuwer")
            return
        }
        guard lopendeSessie == nil else {
            call.reject("Er loopt al een passkey-verzoek")
            return
        }
        guard let optiesJson = call.getString("optiesJson"),
              let optiesData = optiesJson.data(using: .utf8),
              let opties = (try? JSONSerialization.jsonObject(with: optiesData)) as? [String: Any] else {
            call.reject("optiesJson ontbreekt of is geen geldige JSON")
            return
        }

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            do {
                let verzoek: ASAuthorizationRequest = registratie
                    ? try self.maakRegistratieVerzoek(opties)
                    : try self.maakAssertieVerzoek(opties)
                let sessie = PasskeySessie(call: call) { [weak self] in self?.lopendeSessie = nil }
                self.lopendeSessie = sessie
                sessie.voerUit(verzoek)
            } catch let fout as PasskeyOptieFout {
                call.reject(fout.melding)
            } catch {
                call.reject("Passkey-verzoek kon niet opgebouwd worden")
            }
        }
    }

    @available(iOS 16.0, *)
    private func maakRegistratieVerzoek(_ opties: [String: Any]) throws -> ASAuthorizationRequest {
        guard let rp = opties["rp"] as? [String: Any], let rpId = rp["id"] as? String else {
            throw PasskeyOptieFout("rp.id ontbreekt in de registratie-options")
        }
        guard let challengeB64 = opties["challenge"] as? String,
              let challenge = base64urlNaarData(challengeB64) else {
            throw PasskeyOptieFout("challenge ontbreekt of is geen base64url")
        }
        guard let gebruiker = opties["user"] as? [String: Any],
              let naam = gebruiker["name"] as? String,
              let userIdB64 = gebruiker["id"] as? String,
              let userId = base64urlNaarData(userIdB64) else {
            throw PasskeyOptieFout("user.id/user.name ontbreekt in de registratie-options")
        }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
        let verzoek = provider.createCredentialRegistrationRequest(
            challenge: challenge, name: naam, userID: userId
        )
        if let selectie = opties["authenticatorSelection"] as? [String: Any],
           let uv = selectie["userVerification"] as? String {
            verzoek.userVerificationPreference = ASAuthorizationPublicKeyCredentialUserVerificationPreference(uv)
        }
        // excludeCredentials (dubbel-registratie-rem) kan pas vanaf iOS 17.4 doorgegeven
        // worden; de backend weigert een dubbele registratie sowieso server-side.
        if #available(iOS 17.4, *), let uitsluiten = opties["excludeCredentials"] as? [[String: Any]] {
            verzoek.excludedCredentials = uitsluiten.compactMap { descriptor in
                guard let idB64 = descriptor["id"] as? String, let id = base64urlNaarData(idB64) else { return nil }
                return ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: id)
            }
        }
        return verzoek
    }

    @available(iOS 16.0, *)
    private func maakAssertieVerzoek(_ opties: [String: Any]) throws -> ASAuthorizationRequest {
        guard let rpId = opties["rpId"] as? String else {
            throw PasskeyOptieFout("rpId ontbreekt in de assertie-options")
        }
        guard let challengeB64 = opties["challenge"] as? String,
              let challenge = base64urlNaarData(challengeB64) else {
            throw PasskeyOptieFout("challenge ontbreekt of is geen base64url")
        }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
        let verzoek = provider.createCredentialAssertionRequest(challenge: challenge)
        if let toegestaan = opties["allowCredentials"] as? [[String: Any]] {
            verzoek.allowedCredentials = toegestaan.compactMap { descriptor in
                guard let idB64 = descriptor["id"] as? String, let id = base64urlNaarData(idB64) else { return nil }
                return ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: id)
            }
        }
        if let uv = opties["userVerification"] as? String {
            verzoek.userVerificationPreference = ASAuthorizationPublicKeyCredentialUserVerificationPreference(uv)
        }
        return verzoek
    }
}

private struct PasskeyOptieFout: Error {
    let melding: String
    init(_ melding: String) { self.melding = melding }
}

/// Eén OS-prompt-sessie: houdt de Capacitor-call vast, vertaalt het ASAuthorization-resultaat
/// naar de WebAuthn-credential-JSON en ruimt zichzelf op via `klaar`.
private class PasskeySessie: NSObject, ASAuthorizationControllerDelegate,
    ASAuthorizationControllerPresentationContextProviding {

    private let call: CAPPluginCall
    private let klaar: () -> Void

    init(call: CAPPluginCall, klaar: @escaping () -> Void) {
        self.call = call
        self.klaar = klaar
    }

    func voerUit(_ verzoek: ASAuthorizationRequest) {
        let controller = ASAuthorizationController(authorizationRequests: [verzoek])
        controller.delegate = self
        controller.presentationContextProvider = self
        controller.performRequests()
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        let vensters = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
        return vensters.first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        defer { klaar() }
        if #available(iOS 16.0, *) {
            switch authorization.credential {
            case let registratie as ASAuthorizationPlatformPublicKeyCredentialRegistration:
                guard let attestation = registratie.rawAttestationObject else {
                    call.reject("Registratie zonder attestation-object")
                    return
                }
                lever([
                    "id": dataNaarBase64url(registratie.credentialID),
                    "rawId": dataNaarBase64url(registratie.credentialID),
                    "type": "public-key",
                    "clientExtensionResults": [:] as [String: Any],
                    "response": [
                        "clientDataJSON": dataNaarBase64url(registratie.rawClientDataJSON),
                        "attestationObject": dataNaarBase64url(attestation),
                        "transports": ["internal"]
                    ] as [String: Any]
                ])
            case let assertie as ASAuthorizationPlatformPublicKeyCredentialAssertion:
                lever([
                    "id": dataNaarBase64url(assertie.credentialID),
                    "rawId": dataNaarBase64url(assertie.credentialID),
                    "type": "public-key",
                    "clientExtensionResults": [:] as [String: Any],
                    "response": [
                        "clientDataJSON": dataNaarBase64url(assertie.rawClientDataJSON),
                        "authenticatorData": dataNaarBase64url(assertie.rawAuthenticatorData),
                        "signature": dataNaarBase64url(assertie.signature),
                        "userHandle": assertie.userID.isEmpty ? NSNull() : dataNaarBase64url(assertie.userID)
                    ] as [String: Any]
                ])
            default:
                call.reject("Onverwacht credential-type uit de OS-prompt")
            }
        } else {
            call.reject("Passkeys vereisen iOS 16 of nieuwer")
        }
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        defer { klaar() }
        if let asFout = error as? ASAuthorizationError, asFout.code == .canceled {
            // Zelfde toon als het webpad: de schermen herkennen 'geannuleerd' als niet-fout.
            call.reject("Passkey-verzoek geannuleerd")
            return
        }
        call.reject("Passkey-verzoek mislukt: \(error.localizedDescription)")
    }

    private func lever(_ credential: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: credential),
              let json = String(data: data, encoding: .utf8) else {
            call.reject("Credential kon niet geserialiseerd worden")
            return
        }
        call.resolve(["credentialJson": json])
    }
}

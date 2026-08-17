// NatievePasskey — dunne eigen Capacitor-plugin rond de Android Credential Manager
// (androidx.credentials), native store-app fase 2 (GO Peter 2026-08-16).
//
// Contract met de webcode (frontend/src/accordeur/nativePasskey.ts): de py_webauthn-
// options-JSON gaat er byte-exact in; Credential Manager spreekt zelf de WebAuthn-JSON-
// vormen (registrationResponseJson/authenticationResponseJson zijn al exact wat de backend
// verwacht — geen veldvertaling nodig, anders dan op iOS). rp_id blijft de apex (besluit
// 0022); voorwaarde op het toestel: /.well-known/assetlinks.json op de apex mét de
// sha256-vingerafdruk van de signing-key (app/auth/wellknown.py serveert de route).
// VERIFICATIESTATUS: compileert pas met de Android-SDK (lokaal niet aanwezig) — bewijs =
// kliktest-blok fase 2.

package nl.aknijenhuis.goedkeuren;

import androidx.core.content.ContextCompat;
import androidx.credentials.CreateCredentialResponse;
import androidx.credentials.CreatePublicKeyCredentialRequest;
import androidx.credentials.CreatePublicKeyCredentialResponse;
import androidx.credentials.Credential;
import androidx.credentials.CredentialManager;
import androidx.credentials.CredentialManagerCallback;
import androidx.credentials.GetCredentialRequest;
import androidx.credentials.GetCredentialResponse;
import androidx.credentials.GetPublicKeyCredentialOption;
import androidx.credentials.PublicKeyCredential;
import androidx.credentials.exceptions.CreateCredentialCancellationException;
import androidx.credentials.exceptions.CreateCredentialException;
import androidx.credentials.exceptions.GetCredentialCancellationException;
import androidx.credentials.exceptions.GetCredentialException;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.Collections;

@CapacitorPlugin(name = "NatievePasskey")
public class NatievePasskeyPlugin extends Plugin {

    @PluginMethod
    public void registreer(PluginCall call) {
        String optiesJson = call.getString("optiesJson");
        if (optiesJson == null || optiesJson.isEmpty()) {
            call.reject("optiesJson ontbreekt");
            return;
        }
        CredentialManager beheerder = CredentialManager.create(getActivity());
        CreatePublicKeyCredentialRequest verzoek = new CreatePublicKeyCredentialRequest(optiesJson);
        beheerder.createCredentialAsync(
            getActivity(),
            verzoek,
            null,
            ContextCompat.getMainExecutor(getActivity()),
            new CredentialManagerCallback<CreateCredentialResponse, CreateCredentialException>() {
                @Override
                public void onResult(CreateCredentialResponse resultaat) {
                    if (resultaat instanceof CreatePublicKeyCredentialResponse) {
                        lever(call, ((CreatePublicKeyCredentialResponse) resultaat).getRegistrationResponseJson());
                    } else {
                        call.reject("Onverwacht credential-type uit Credential Manager");
                    }
                }

                @Override
                public void onError(CreateCredentialException fout) {
                    if (fout instanceof CreateCredentialCancellationException) {
                        // Zelfde toon als het webpad: schermen herkennen 'geannuleerd'.
                        call.reject("Passkey-registratie geannuleerd");
                    } else {
                        call.reject("Passkey-registratie mislukt: " + fout.getMessage());
                    }
                }
            }
        );
    }

    @PluginMethod
    public void onderteken(PluginCall call) {
        String optiesJson = call.getString("optiesJson");
        if (optiesJson == null || optiesJson.isEmpty()) {
            call.reject("optiesJson ontbreekt");
            return;
        }
        CredentialManager beheerder = CredentialManager.create(getActivity());
        GetCredentialRequest verzoek = new GetCredentialRequest(
            Collections.singletonList(new GetPublicKeyCredentialOption(optiesJson))
        );
        beheerder.getCredentialAsync(
            getActivity(),
            verzoek,
            null,
            ContextCompat.getMainExecutor(getActivity()),
            new CredentialManagerCallback<GetCredentialResponse, GetCredentialException>() {
                @Override
                public void onResult(GetCredentialResponse resultaat) {
                    Credential credential = resultaat.getCredential();
                    if (credential instanceof PublicKeyCredential) {
                        lever(call, ((PublicKeyCredential) credential).getAuthenticationResponseJson());
                    } else {
                        call.reject("Onverwacht credential-type uit Credential Manager");
                    }
                }

                @Override
                public void onError(GetCredentialException fout) {
                    if (fout instanceof GetCredentialCancellationException) {
                        call.reject("Passkey-verificatie geannuleerd");
                    } else {
                        call.reject("Passkey-verificatie mislukt: " + fout.getMessage());
                    }
                }
            }
        );
    }

    private void lever(PluginCall call, String credentialJson) {
        JSObject resultaat = new JSObject();
        resultaat.put("credentialJson", credentialJson);
        call.resolve(resultaat);
    }
}

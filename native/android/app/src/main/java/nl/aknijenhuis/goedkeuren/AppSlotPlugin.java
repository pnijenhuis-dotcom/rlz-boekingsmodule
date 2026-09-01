// AppSlot — biometrie-gemakslaag van het app-lock (besluit Peter 31-08, mockup
// app-lock-pincode.html). Bewaart een kopie van het lokale anker versleuteld met een
// Keystore-sleutel die BiometricPrompt-authenticatie vereist; de 5-cijferige code blijft het
// altijd-werkende pad (webcode, PBKDF2-wrap in VeiligeOpslag).
//
// HARDE EIS (mockup-notitie ②): setInvalidatedByBiometricEnrollment(false) — een nieuw
// ingeschreven gezicht/vingerafdruk maakt de kopie nooit onbruikbaar. Zelfde
// geen-community-pakket-lijn als NatievePasskey/VeiligeOpslag.
// VERIFICATIESTATUS: compileert pas met de Android-SDK — bewijs = kliktest-blok app-lock.

package nl.aknijenhuis.goedkeuren;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.FragmentActivity;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.security.KeyStore;
import java.util.concurrent.Executor;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

@CapacitorPlugin(name = "AppSlot")
public class AppSlotPlugin extends Plugin {

    private static final String SLEUTEL_ALIAS = "appslot_biometrie";
    private static final String OPSLAG_NAAM = "appslot_bio";
    private static final String OPSLAG_IV = "iv";
    private static final String OPSLAG_CIPHER = "cipher";

    private SharedPreferences opslag() {
        return getContext().getSharedPreferences(OPSLAG_NAAM, Context.MODE_PRIVATE);
    }

    /** Badge-count (best-practice-punt D4, 01-09). Android kent geen los badge-veld: launchers volgen de
     *  notificaties (FCM `notification_count`) — 0 = alle afgeleverde meldingen opruimen zodat de badge
     *  verdwijnt; > 0 = de afgeleverde meldingen dragen het aantal al. Fail-stil. */
    @PluginMethod
    public void zetBadge(PluginCall call) {
        int aantal = Math.max(0, call.getInt("aantal", 0));
        try {
            if (aantal == 0) {
                androidx.core.app.NotificationManagerCompat.from(getContext()).cancelAll();
            }
        } catch (RuntimeException e) {
            // gemak, nooit een blokkade
        }
        call.resolve();
    }

    @PluginMethod
    public void beschikbaar(PluginCall call) {
        int status = BiometricManager.from(getContext())
            .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG);
        JSObject resultaat = new JSObject();
        resultaat.put("beschikbaar", status == BiometricManager.BIOMETRIC_SUCCESS);
        // Android maakt gezicht/vinger niet betrouwbaar onderscheidbaar — de UI-tekst zegt
        // daarom generiek "vingerafdruk of gezicht" (mockup scherm 7).
        resultaat.put("soort", "biometrie");
        call.resolve(resultaat);
    }

    private SecretKey maakSleutel() throws Exception {
        KeyGenerator generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        KeyGenParameterSpec.Builder spec = new KeyGenParameterSpec.Builder(
                SLEUTEL_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setUserAuthenticationRequired(true)
            // Harde eis: her-inschrijving van biometrie sluit nooit uit.
            .setInvalidatedByBiometricEnrollment(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            spec.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG);
        } else {
            spec.setUserAuthenticationValidityDurationSeconds(-1);
        }
        generator.init(spec.build());
        return generator.generateKey();
    }

    private SecretKey haalKeystoreSleutel() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        KeyStore.Entry entry = keyStore.getEntry(SLEUTEL_ALIAS, null);
        if (entry instanceof KeyStore.SecretKeyEntry) {
            return ((KeyStore.SecretKeyEntry) entry).getSecretKey();
        }
        return null;
    }

    private void toonPrompt(PluginCall call, Cipher cipher, String reden,
                            BiometricPrompt.AuthenticationCallback callback) {
        FragmentActivity activiteit = getActivity();
        if (activiteit == null) {
            call.reject("mislukt: geen activiteit");
            return;
        }
        activiteit.runOnUiThread(() -> {
            Executor executor = ContextCompat.getMainExecutor(getContext());
            BiometricPrompt prompt = new BiometricPrompt(activiteit, executor, callback);
            BiometricPrompt.PromptInfo info = new BiometricPrompt.PromptInfo.Builder()
                .setTitle(reden)
                // Geen OS-terugvalknop naar de toestel-pincode: de code-terugval is ons eigen
                // scherm (mockup 5) — de annuleerknop brengt de gebruiker daar.
                .setNegativeButtonText("Code gebruiken")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .build();
            prompt.authenticate(info, new BiometricPrompt.CryptoObject(cipher));
        });
    }

    @PluginMethod
    public void zetSleutel(PluginCall call) {
        String waarde = call.getString("waarde");
        if (waarde == null) {
            call.reject("waarde ontbreekt");
            return;
        }
        try {
            SecretKey sleutel = maakSleutel(); // vers — vervangt een eventuele oude alias
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, sleutel);
            toonPrompt(call, cipher, "Face ID/vingerafdruk aanzetten", new BiometricPrompt.AuthenticationCallback() {
                @Override
                public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                    try {
                        Cipher geautoriseerd = result.getCryptoObject().getCipher();
                        byte[] versleuteld = geautoriseerd.doFinal(waarde.getBytes("UTF-8"));
                        opslag().edit()
                            .putString(OPSLAG_IV, Base64.encodeToString(geautoriseerd.getIV(), Base64.NO_WRAP))
                            .putString(OPSLAG_CIPHER, Base64.encodeToString(versleuteld, Base64.NO_WRAP))
                            .apply();
                        call.resolve();
                    } catch (Exception fout) {
                        call.reject("mislukt: " + fout.getMessage());
                    }
                }

                @Override
                public void onAuthenticationError(int code, CharSequence melding) {
                    call.reject(code == BiometricPrompt.ERROR_NEGATIVE_BUTTON
                        || code == BiometricPrompt.ERROR_USER_CANCELED
                        ? "geannuleerd" : "mislukt: " + melding);
                }
            });
        } catch (Exception fout) {
            call.reject("mislukt: " + fout.getMessage());
        }
    }

    @PluginMethod
    public void haalSleutel(PluginCall call) {
        String reden = call.getString("reden", "Ontgrendel de app");
        try {
            String ivB64 = opslag().getString(OPSLAG_IV, null);
            String cipherB64 = opslag().getString(OPSLAG_CIPHER, null);
            SecretKey sleutel = haalKeystoreSleutel();
            if (ivB64 == null || cipherB64 == null || sleutel == null) {
                JSObject leeg = new JSObject();
                leeg.put("waarde", JSObject.NULL);
                call.resolve(leeg);
                return;
            }
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, sleutel,
                new GCMParameterSpec(128, Base64.decode(ivB64, Base64.NO_WRAP)));
            byte[] versleuteld = Base64.decode(cipherB64, Base64.NO_WRAP);
            toonPrompt(call, cipher, reden, new BiometricPrompt.AuthenticationCallback() {
                @Override
                public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                    try {
                        byte[] klaar = result.getCryptoObject().getCipher().doFinal(versleuteld);
                        JSObject resultaat = new JSObject();
                        resultaat.put("waarde", new String(klaar, "UTF-8"));
                        call.resolve(resultaat);
                    } catch (Exception fout) {
                        call.reject("mislukt: " + fout.getMessage());
                    }
                }

                @Override
                public void onAuthenticationError(int code, CharSequence melding) {
                    call.reject(code == BiometricPrompt.ERROR_NEGATIVE_BUTTON
                        || code == BiometricPrompt.ERROR_USER_CANCELED
                        ? "geannuleerd" : "mislukt: " + melding);
                }
            });
        } catch (Exception fout) {
            // Bv. een tóch ongeldig geworden Keystore-sleutel: gedraag je als "geen kopie" —
            // de webcode valt dan stil terug op de code (nooit uitsluiten).
            JSObject leeg = new JSObject();
            leeg.put("waarde", JSObject.NULL);
            call.resolve(leeg);
        }
    }

    @PluginMethod
    public void wisSleutel(PluginCall call) {
        try {
            opslag().edit().clear().apply();
            KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
            keyStore.load(null);
            if (keyStore.containsAlias(SLEUTEL_ALIAS)) {
                keyStore.deleteEntry(SLEUTEL_ALIAS);
            }
            call.resolve();
        } catch (Exception fout) {
            call.reject("Verwijderfout: " + fout.getMessage());
        }
    }
}

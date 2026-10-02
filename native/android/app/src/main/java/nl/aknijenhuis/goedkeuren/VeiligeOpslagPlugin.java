// VeiligeOpslag — dunne eigen Capacitor-plugin rond EncryptedSharedPreferences (Keystore-
// gedekte AES-sleutel), store-app fase 4. Bewaart het refresh-token van de apparaat-gebonden
// sessie (verkenning/17 (d) route 2). Zelfde geen-community-pakket-lijn als NatievePasskey.
// VERIFICATIESTATUS: compileert pas met de Android-SDK — bewijs = kliktest-blok fase 4.
//
// Zelfherstel van de kluis (native 1.3 / vc7, run D 02-10, bug Peter 02-10 "Opslag-verwijderfout: null"):
// als EncryptedSharedPreferences niet te openen is (MasterKey/Keystore-sleutel ongeldig of weg ná een
// backup-herstel, toestel-overdracht of OS-update — AEADBadTagException, KeyStoreException, GeneralSecurityException,
// vaak mét getMessage() == null), dan is de inhoud toch onleesbaar: het bestand `veilige_opslag` wordt ÉÉN keer
// gewist en opnieuw aangemaakt vóór de aanroep faalt. Daarnaast de expliciete methode `herstel` (knop in de app).
// Een foutmelding is nooit "null": `<klasse>: <message>` of `<klasse> (zonder melding)`.

package nl.aknijenhuis.goedkeuren;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.security.KeyStore;

@CapacitorPlugin(name = "VeiligeOpslag")
public class VeiligeOpslagPlugin extends Plugin {

    /** Naam van het EncryptedSharedPreferences-bestand (óók uitgesloten van backup: res/xml/backup_rules.xml,
     *  res/xml/data_extraction_rules.xml). */
    static final String OPSLAG_NAAM = "veilige_opslag";
    /** Alias van de MasterKey die androidx.security standaard gebruikt (MasterKey.DEFAULT_MASTER_KEY_ALIAS). */
    static final String MASTER_KEY_ALIAS = MasterKey.DEFAULT_MASTER_KEY_ALIAS;

    /** Opent de kluis; één keer een zelfherstel-poging als openen faalt (zie klasse-commentaar). */
    private SharedPreferences opslag() throws Exception {
        try {
            return openKluis();
        } catch (Exception eersteFout) {
            // De inhoud is zonder werkende sleutel onleesbaar — wissen kost niets wat nog bruikbaar was.
            wisKluisBestand();
            try {
                return openKluis();
            } catch (Exception tweedeFout) {
                throw new Exception(
                    "kluis niet te openen ná herstel (" + foutTekst(eersteFout) + " → " + foutTekst(tweedeFout) + ")",
                    tweedeFout
                );
            }
        }
    }

    private SharedPreferences openKluis() throws Exception {
        MasterKey sleutel = new MasterKey.Builder(getContext(), MASTER_KEY_ALIAS)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build();
        return EncryptedSharedPreferences.create(
            getContext(),
            OPSLAG_NAAM,
            sleutel,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        );
    }

    /** Wist het prefs-bestand (API 24+: deleteSharedPreferences; ouder: bestand zelf) — nooit een exception naar buiten. */
    private void wisKluisBestand() {
        Context context = getContext();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                context.deleteSharedPreferences(OPSLAG_NAAM);
            } else {
                context.getSharedPreferences(OPSLAG_NAAM, Context.MODE_PRIVATE).edit().clear().commit();
                File bestand = new File(new File(context.getApplicationInfo().dataDir, "shared_prefs"), OPSLAG_NAAM + ".xml");
                //noinspection ResultOfMethodCallIgnored
                bestand.delete();
            }
        } catch (Exception genegeerd) {
            // best-effort: het bestand kan al weg zijn
        }
    }

    /** Verwijdert óók de MasterKey uit de AndroidKeyStore, zodat een corrupte/ongeldige sleutel niet opnieuw gebruikt wordt
     *  (alleen bij het EXPLICIETE herstel — de impliciete poging in opslag() houdt de sleutel: die is meestal gewoon goed
     *  en alleen het bestand past er niet meer bij). */
    private void wisMasterKey() {
        try {
            KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
            keyStore.load(null);
            if (keyStore.containsAlias(MASTER_KEY_ALIAS)) {
                keyStore.deleteEntry(MASTER_KEY_ALIAS);
            }
        } catch (Exception genegeerd) {
            // best-effort
        }
    }

    /** Foutmelding nooit "null": klassenaam + bericht. */
    static String foutTekst(Throwable fout) {
        if (fout == null) {
            return "onbekende fout";
        }
        String klasse = fout.getClass().getSimpleName();
        String bericht = fout.getMessage();
        if (bericht == null || bericht.trim().isEmpty()) {
            Throwable oorzaak = fout.getCause();
            if (oorzaak != null && oorzaak != fout && oorzaak.getMessage() != null && !oorzaak.getMessage().trim().isEmpty()) {
                return klasse + ": " + oorzaak.getClass().getSimpleName() + ": " + oorzaak.getMessage();
            }
            return klasse + " (zonder melding)";
        }
        return klasse + ": " + bericht;
    }

    @PluginMethod
    public void zet(PluginCall call) {
        String sleutel = call.getString("sleutel");
        String waarde = call.getString("waarde");
        if (sleutel == null || waarde == null) {
            call.reject("sleutel/waarde ontbreekt");
            return;
        }
        try {
            opslag().edit().putString(sleutel, waarde).apply();
            call.resolve();
        } catch (Exception fout) {
            call.reject("Opslag-schrijffout: " + foutTekst(fout));
        }
    }

    @PluginMethod
    public void haal(PluginCall call) {
        String sleutel = call.getString("sleutel");
        if (sleutel == null) {
            call.reject("sleutel ontbreekt");
            return;
        }
        try {
            String waarde = opslag().getString(sleutel, null);
            JSObject resultaat = new JSObject();
            resultaat.put("waarde", waarde == null ? JSObject.NULL : waarde);
            call.resolve(resultaat);
        } catch (Exception fout) {
            call.reject("Opslag-leesfout: " + foutTekst(fout));
        }
    }

    @PluginMethod
    public void verwijder(PluginCall call) {
        String sleutel = call.getString("sleutel");
        if (sleutel == null) {
            call.reject("sleutel ontbreekt");
            return;
        }
        try {
            opslag().edit().remove(sleutel).apply();
            call.resolve();
        } catch (Exception fout) {
            call.reject("Opslag-verwijderfout: " + foutTekst(fout));
        }
    }

    /** Expliciet herstel (knop "App-opslag opnieuw instellen", native 1.3): kluisbestand + MasterKey weg, kluis opnieuw
     *  aangemaakt en bewezen schrijfbaar/leesbaar. Alles wat erin stond (toestel-token, slot) is daarna weg — de app start
     *  de activatieflow; het toestel-token zelf blijft server-side geldig tot het kantoor het intrekt. */
    @PluginMethod
    public void herstel(PluginCall call) {
        wisKluisBestand();
        wisMasterKey();
        try {
            SharedPreferences kluis = openKluis();
            kluis.edit().putString("_herstel_proef", "1").apply();
            boolean leesbaar = "1".equals(kluis.getString("_herstel_proef", null));
            kluis.edit().remove("_herstel_proef").apply();
            if (!leesbaar) {
                call.reject("Opslag-herstelfout: kluis opnieuw aangemaakt maar niet leesbaar");
                return;
            }
            JSObject resultaat = new JSObject();
            resultaat.put("hersteld", true);
            call.resolve(resultaat);
        } catch (Exception fout) {
            call.reject("Opslag-herstelfout: " + foutTekst(fout));
        }
    }
}

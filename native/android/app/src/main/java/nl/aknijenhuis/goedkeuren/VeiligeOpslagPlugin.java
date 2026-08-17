// VeiligeOpslag — dunne eigen Capacitor-plugin rond EncryptedSharedPreferences (Keystore-
// gedekte AES-sleutel), store-app fase 4. Bewaart het refresh-token van de apparaat-gebonden
// sessie (verkenning/17 (d) route 2). Zelfde geen-community-pakket-lijn als NatievePasskey.
// VERIFICATIESTATUS: compileert pas met de Android-SDK — bewijs = kliktest-blok fase 4.

package nl.aknijenhuis.goedkeuren;

import android.content.SharedPreferences;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "VeiligeOpslag")
public class VeiligeOpslagPlugin extends Plugin {

    private SharedPreferences opslag() throws Exception {
        MasterKey sleutel = new MasterKey.Builder(getContext())
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build();
        return EncryptedSharedPreferences.create(
            getContext(),
            "veilige_opslag",
            sleutel,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        );
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
            call.reject("Opslag-schrijffout: " + fout.getMessage());
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
            call.reject("Opslag-leesfout: " + fout.getMessage());
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
            call.reject("Opslag-verwijderfout: " + fout.getMessage());
        }
    }
}

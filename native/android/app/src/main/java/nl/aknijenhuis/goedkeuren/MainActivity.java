package nl.aknijenhuis.goedkeuren;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // In-app-plugins registreren vóór de bridge laadt (Capacitor-conventie).
        registerPlugin(NatievePasskeyPlugin.class);
        registerPlugin(VeiligeOpslagPlugin.class);
        registerPlugin(AppSlotPlugin.class);
        super.onCreate(savedInstanceState);
    }
}

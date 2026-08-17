// Registratie van in-app-Capacitor-plugins (Capacitor ≥ 6: plugins die ín het app-target
// leven worden niet auto-ontdekt — registratie hoort in capacitorDidLoad van de bridge-VC;
// Main.storyboard wijst naar deze klasse).

import Capacitor

class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(NatievePasskeyPlugin())
    }
}

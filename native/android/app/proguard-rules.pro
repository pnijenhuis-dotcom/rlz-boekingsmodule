# R8-configuratie release (Play-nazorg 30-08) — IDENTITEITSMODUS.
#
# Doel: een mapping.txt (deobfuscation-bestand) voor Play Console zónder de app te veranderen.
# De app is een JS-bundel in een dunne Capacitor-schil; het Java-oppervlak (twee eigen plugins,
# Capacitor, Firebase Messaging, Credential Manager) wordt bewust NIET geobfusceerd of
# geshrinkt: leesbare stacktraces in Play Vitals wegen zwaarder dan een paar honderd kB, en
# shrinken zou een reflectie-afhankelijkheid (Capacitor-pluginregistratie, Cordova-bridge)
# alleen op een toestel kunnen breken — dát is een apart besluit mét emulator-kliktest.
-dontobfuscate
-dontoptimize
-dontshrink
# Bron-/regelinformatie behouden: stacktraces uit Play Vitals wijzen naar de echte regel.
-keepattributes SourceFile,LineNumberTable
# Eigen Capacitor-plugins (NatievePasskeyPlugin, VeiligeOpslagPlugin) expliciet vasthouden —
# belt-and-braces bovenop de consumer-rules van capacitor-android, voor als shrinken ooit aangaat.
-keep @com.getcapacitor.annotation.CapacitorPlugin public class nl.aknijenhuis.goedkeuren.** { *; }
# Ontbrekende OPTIONELE afhankelijkheden (R8 "Missing classes", eerste identiteitsbuild 30-08):
# Tink (via androidx.security:security-crypto) verwijst naar google-http-client + joda-time voor
# zijn KeysDownloader (remote-keysets — gebruiken wij niet), Firebase Installations naar de
# Kotlin-ktx-shim. Die klassen zitten niet in de app en worden nooit aangeroepen; zonder
# -dontwarn weigert R8 te compileren. Geen keep-regels — alleen het waarschuwingsniveau.
-dontwarn com.google.api.client.http.GenericUrl
-dontwarn com.google.api.client.http.HttpHeaders
-dontwarn com.google.api.client.http.HttpRequest
-dontwarn com.google.api.client.http.HttpRequestFactory
-dontwarn com.google.api.client.http.HttpResponse
-dontwarn com.google.api.client.http.HttpTransport
-dontwarn com.google.api.client.http.javanet.NetHttpTransport$Builder
-dontwarn com.google.api.client.http.javanet.NetHttpTransport
-dontwarn com.google.firebase.ktx.Firebase
-dontwarn org.joda.time.Instant

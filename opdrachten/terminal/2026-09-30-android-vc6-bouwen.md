# Terminal 30-09 — Android 1.2 (vc6) bouwen voor Play (mét OTA + in-app-update + FCM)

Claude Code voert uit mét toestemming per commando; niets wordt gecommit of geüpload — de upload doet Peter in de Play Console.
Repo-root: /Users/mr.x/Claude/Projects/Rlz boekings module

## Stap 1 — omgeving (per shell)
```
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
java -version
test -f "/Users/mr.x/Claude/Projects/Rlz boekings module/native/android/keystore.properties" && echo "keystore.properties: aanwezig"
```
Verwacht: `openjdk 21…` en "keystore.properties: aanwezig". Ontbreekt de keystore: STOP, PLAY_DRAAIBOEK §2.

## Stap 2 — schone werkboom + juiste bron
```
git -C "/Users/mr.x/Claude/Projects/Rlz boekings module" status --short
git -C "/Users/mr.x/Claude/Projects/Rlz boekings module" log --oneline -1
grep -n "versionCode\|versionName" "/Users/mr.x/Claude/Projects/Rlz boekings module/native/android/app/build.gradle" | grep -v "^.*//"
```
Verwacht: geen wijzigingen, HEAD = 8e58df9 of nieuwer, defaults versionCode 6 / versionName "1.2".

## Stap 3 — bouwen (10–15 min)
```
cd "/Users/mr.x/Claude/Projects/Rlz boekings module" && native/scripts/bouw_android_release.sh 6 1.2
```
Verwacht aan het einde: pad `native/android/app/release/nijenhuis-goedkeuren-1.2-vc6-<datum>.aab` + SHA-256, signatuur = upload-key
(`4A:B4:3C:…:8F:A1`), bundletool validate ✓, versionCode 6 · versionName 1.2 ✓, `capacitor.plugins.json` noemt
`@capgo/capacitor-updater` en `@capawesome/capacitor-app-update`. Eén rood = niet uploaden, uitvoer aan Cowork.

## Stap 4 — controle dat de OTA-plugins er écht in zitten
```
ls -la "/Users/mr.x/Claude/Projects/Rlz boekings module/native/android/app/release/" | tail -5
unzip -p "$(ls -t "/Users/mr.x/Claude/Projects/Rlz boekings module"/native/android/app/release/*.aab | head -1)" base/assets/capacitor.plugins.json
```
Verwacht: JSON mét `CapacitorUpdater` en `AppUpdate`.

Daarna: Peter uploadt de .aab + de `-native-debug-symbols.zip` in de Play Console (stappen in het gesprek van 30-09).

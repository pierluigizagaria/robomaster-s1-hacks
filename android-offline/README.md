# APK RoboMaster originale senza login

Ultimo aggiornamento: 28 settembre 2026.

Richiesta privata dell'operatore per telefono Android e Meta Quest 3, separata
dal controller Godot. La copia mantiene l'app DJI originale, la sua interfaccia
Android e il package `com.dji.robomaster`; sul Quest non diventa un'app OpenXR.

## Artefatto e stato

- APK corrente: `android-offline/build/RoboMaster-1.2.0-offline-r2.apk`.
- Versione originale: 1.2.0, versionCode 382; ARM64 e ARMv7 nello stesso APK.
- Dimensione: 426.557.899 byte.
- SHA-256: `CF19708A115AEFEA23E61246DD543C9831A4E156E5DC70E41474BBAE1AAD3D1E`.
- Firma personale debug, schemi v1/v2/v3 verificati; allineamento verificato.
- Otto test Python PASS, con transizioni ARM64/ARMv7 e bootstrap ARM64/Thumb in Unicorn.
- Confronto completo di 6.469 entry del payload prima della firma: cambiano
  le due `libil2cpp.so` e le due `libbaiduprotect.so`; audit firmato in
  `android-offline/build/signed-apk-audit-r2.json`.
- **R2 installata come aggiornamento sul Quest 3 il 28 settembre 2026**, con
  hash del `base.apk` coincidente e senza un altro reset dei dati. Primo avvio
  21:05:31 CEST, ripresa dal sonno 21:06:22: Unity inizializzata e scena
  `ViewLoginAndRegister` caricata, processo persistente senza SIGABRT.
  Verifica visiva, completamento del consenso/menu, telefono e funzioni robot
  restano da collaudare. La cattura del display fisico Quest è nera e non
  costituisce prova della schermata mostrata nel visore.

## Comportamento

L'avvio usa la scelta privacy locale al posto dello stato dell'account. Se
l'informativa è già stata accettata apre il menu. Su un'installazione nuova
conserva la scena originale che mostra l'informativa; il suo aggiornamento
attende la scelta dell'utente e poi passa al menu, senza autenticazione.
Il controllo remoto del token all'ingresso del menu è rimosso. Token non valido
e logout portano al menu. Non vengono inventati token, profili o flag di login
e non viene accettata automaticamente l'informativa.

La prima informativa rimane nella scena DJI `LoginAndRegister`: la schermata
di accesso può comparire brevemente durante quella transizione. La prova
reale deve verificare ordine dei dialoghi, completamento del primo avvio,
riavvio senza rete e inizializzazione dei servizi robot. Le funzioni online
che richiedono un account non sono rese disponibili dalla patch.

Diversamente dalla patch Windows, Android usa già `persistentDataPath` per i
dati locali: nessuna modifica ai percorsi. Manifest, risorse, metadata IL2CPP,
DEX, librerie robot e asset rimangono identici all'originale.

### Correzione del crash all'avvio (r2)

La prima APK `C35EE0A2…9EABDE60` era installabile ma falliva al primo avvio:
`XOX: state=526` seguito da SIGABRT entro circa due secondi, riprodotto via ADB.
Il bootstrap Baidu confronta il certificato con quello DJI. La prova intermedia
con il solo controllo del certificato adattato ha prodotto `state=527` per
le entry ZIP ricostruite. La r2 modifica tre funzioni di controllo locale
(certificato, digest delle entry, inventario ZIP) in ciascuna ABI. Conserva
caricamento delle classi, consenso privacy e verifiche di firma di Android.
Il patcher verifica invece fonte, librerie e intero payload prima della firma.
Questa copia personale non va descritta come un pacchetto autenticato da DJI.

Le funzioni ARM64 sono a RVA `0x22C68`, `0x2307C`, `0x237E4`; le Thumb a
`0x17D0C`, `0x18030`, `0x1852C`. Il codice del bootstrap è memorizzato a byte
invertiti: le patch agiscono sulle corrispondenti posizioni nel file. I test
riproducono questa trasformazione e verificano ritorno, stack e registri.
Log delle riproduzioni fallite e dell'avvio r2 in
`android-offline/build/crash-20260928/`; nessuna prova robot eseguita.

## Riproduzione privata

`android-offline/scripts/patch_original_android_offline.py` usa soltanto Python 3.11+ standard.
Richiede l'APK originale dell'operatore, controlla SHA-256 dell'intero APK,
hash delle librerie e byte di ogni punto modificato. Rifiuta versioni diverse,
input già modificati e output esistenti. Non sovrascrive l'originale.

```powershell
python android-offline/scripts/patch_original_android_offline.py `
  "<ORIGINAL_APK>" `
  android-offline/build/RoboMaster-1.2.0-offline-r2-unsigned.apk

python android-offline/scripts/verify_original_android_offline.py `
  "<ORIGINAL_APK>"

$buildTools = '<ANDROID_SDK>/build-tools/36.1.0'
& "$buildTools/zipalign.exe" -p 4 `
  android-offline/build/RoboMaster-1.2.0-offline-r2-unsigned.apk `
  android-offline/build/RoboMaster-1.2.0-offline-r2-aligned.apk
java -jar "$buildTools/lib/apksigner.jar" sign `
  --ks <DEBUG_KEYSTORE> --ks-key-alias androiddebugkey `
  --ks-pass pass:android --key-pass pass:android `
  --out android-offline/build/RoboMaster-1.2.0-offline-r2.apk `
  android-offline/build/RoboMaster-1.2.0-offline-r2-aligned.apk
java -jar "$buildTools/lib/apksigner.jar" verify --verbose `
  android-offline/build/RoboMaster-1.2.0-offline-r2.apk
& "$buildTools/zipalign.exe" -c -p 4 `
  android-offline/build/RoboMaster-1.2.0-offline-r2.apk
```

I test privati richiedono Unicorn e l'APK locale, senza robot. Simulano la
lettura del consenso e l'ingresso nelle funzioni Unity: verificano istruzioni,
rami, integrità dello stack e registri, non il funzionamento di Android/Unity.
Analisi di metodi e indirizzi ottenuta con
[Il2CppDumper 6.7.46](https://github.com/Perfare/Il2CppDumper/releases/tag/v6.7.46)
e disassemblaggio Capstone; dump e binari sotto
`android-offline/build/private_reference/`, ignorato da Git.

SHA-256 APK sorgente:
`82C86A9E77C4DBF9FB4C18660B3D0FBBFD6095C4C4B0EB03E9B2C6AAE13059A1`.
Dettaglio di offset, istruzioni prima/dopo e hash delle librerie nel rapporto
`android-offline/build/patch-report-r2.json`. Log test e firma nella
stessa directory. Gli avvisi apksigner sui file AndroidX `META-INF/*.version`
riguardano lo schema JAR v1; la verifica v2/v3 dell'APK completo passa.

## Installazione iniziale e conservazione dei dati

La firma personale è diversa dalla firma DJI: l'APK non aggiorna direttamente
una copia firmata DJI. L'operatore ha autorizzato esplicitamente la sostituzione
e l'azzeramento delle preferenze interne non recuperabili. Sul visore di prova
è stata disinstallata la copia DJI 1.2.0/382 e installata la copia offline.
Il package Godot `com.robomaster.questcontroller` non è stato modificato.

Prima della sostituzione sono stati salvati l'APK precedente (hash identico
all'originale in Downloads) e tutti i 3.067 file esterni, 145.658.593 byte.
Ripristinati tutti i file esterni con hash individuali coincidenti. Il push ADB
delle directory ha incontrato `secure_mkdirs`; il ripristino è riuscito con un
archivio tar estratto dalla shell, poi rimosso dalla directory temporanea Quest.
Le preferenze interne non erano leggibili (`run-as` negato, app non debuggable)
e sono state azzerate come autorizzato. Non è stato accettato alcun dialogo.

Backup e audit per file: `android-offline/build/private_reference/quest-before-install/`.
Log installazione: `android-offline/build/quest-install.log`.
Audit finale: `android-offline/build/quest-installed-apk-audit.json`:
hash APK coincidente, dati esterni ripristinati, `stopped=true`, `notLaunched=true`,
nessun processo RoboMaster. **PASS del solo deployment.**

La r2 successiva usa `adb install --no-incremental -r` con la medesima firma
personale: nessuna disinstallazione e nessun secondo reset delle preferenze.
Audit corrente: `android-offline/build/quest-installed-apk-audit-r2.json`.

Collaudo successivo sul Quest e, dopo installazione, sul telefono: scelta privacy,
menu senza credenziali, riavvio senza Internet, logout; poi verifica separata
delle funzioni robot. Una prova di questa app non convalida il controller Godot.

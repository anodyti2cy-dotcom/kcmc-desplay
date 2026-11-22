# Mfumo wa TAG KCMC

## Kuanzisha kwenye kompyuta

1. Hakikisha Python 3 imewekwa.
2. Endesha `anza.bat`.
3. Mara ya kwanza, tengeneza akaunti ya mwalimu kwa jina la mtumiaji, nenosiri lenye angalau herufi 10 na picha ya wasifu.
4. Baadaye, ingia kwa akaunti hiyo. Baada ya kuingia, kitufe cha **WASHA TV** hufungua skrini ya kuonesha.

Seva hutumia SQLite na huunda `kanisa.sqlite3` ndani ya folda ya mfumo. Nenosiri halihifadhiwi kama maandishi; seva huhifadhi hash ya PBKDF2. Picha ya wasifu na mapendeleo huhifadhiwa kwenye hifadhidata hiyo. Hifadhi nakala salama ya faili la SQLite pamoja na mradi.

## Mtandao na HTTPS

Kwa chaguo-msingi, seva husikiliza kwenye `127.0.0.1` pekee. Hii hulinda taarifa za kuingia zisipite kwenye mtandao bila usimbaji fiche. Usibadilishe seva isikilize kwenye anwani ya mtandao bila HTTPS.

Kwa matumizi ya vifaa vingine, tumia seva/hosting yenye HTTPS. Ikiwa unaendesha TLS moja kwa moja kupitia seva hii, weka vyeti kabla ya kuanzisha:

```powershell
$env:KANISA_HOST = "0.0.0.0"
$env:KANISA_PORT = "5500"
$env:KANISA_TLS_CERT = "C:\njia\ya\cheti.pem"
$env:KANISA_TLS_KEY = "C:\njia\ya\ufunguo.pem"
$env:KANISA_SETUP_TOKEN = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
python server.py
```

Ikiwa HTTPS inasimamiwa na reverse proxy, acha seva hii kwenye `127.0.0.1`, weka `KANISA_COOKIE_SECURE=1`, `KANISA_PUBLIC_ORIGIN` iwe origin kamili ya HTTPS (mfano `https://kanisa.example.org`) na weka `KANISA_SETUP_TOKEN` kwa mfano ulio juu. Proxy lazima ielekeze maombi ya programu kwa seva hii.

Msimbo wa `KANISA_SETUP_TOKEN` huhitajika kwa usanidi wa kwanza wa seva inayofikiwa kupitia mtandao; usiushiriki hadharani. Akaunti ya kwanza pekee ndiyo inaweza kuanzishwa, kisha msimbo huo hauhitajiki tena. Akaunti nyingine haziwezi kujisajili. `KANISA_DB_PATH` inaweza kuwekwa ili kuchagua mahali tofauti pa hifadhidata; mfumo huu kwa sasa ni wa akaunti moja ya mwalimu kwa kila hifadhidata.

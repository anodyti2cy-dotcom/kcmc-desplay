# Mfumo wa TAG KCMC

Mfumo huu ni tovuti tuli (HTML, CSS na JavaScript). Hauhitaji seva ya Node.js, Python wala hifadhidata. Mipangilio (jina, picha ya wasifu, lugha, mandhari), matangazo, nyimbo na mipangilio ya TV huhifadhiwa kwenye kivinjari (localStorage) cha kompyuta unayotumia.

## Faili za mfumo

- `index.html`: ukurasa wa mwalimu
- `tv.html`: skrini ya TV (hufunguliwa na kitufe cha **WASHA TV**, mawasiliano kwa BroadcastChannel)
- `camera.html`: kamera ya simu
- `biblia.xml`: Biblia ya Kiswahili
- `tenzi-data.json`: nyimbo (weka kwenye folda ile ile kama zipo)
- `nembo.png`: nembo
- `login.html`: inaelekeza kwenye `index.html` tu (kwa viungo vya zamani)

## Kuendesha kwenye kompyuta

1. Hakikisha Python 3 imewekwa.
2. Bonyeza mara mbili `anza.bat`. Hufungua `http://127.0.0.1:5500/index.html`.

## Kupeleka kwenye Vercel (kupitia GitHub)

1. Pakia faili zote za folda hii kwenye GitHub repository.
2. Kwenye Vercel, ingiza repository. **Framework Preset**: Other. Acha Build Command na Output Directory wazi.
3. Deploy. Hakuna Environment Variables zinazohitajika.

Hakikisha repository haina tena `api/`, `server.py`, `vercel.json` ya zamani (yenye `rewrites` za `/api/...`), `package-lock.json` ya zamani wala `kanisa.sqlite3`.

## Kumbuka

- Data huhifadhiwa kwa kila kivinjari na kila anwani (domain). Ukitumia kompyuta au kivinjari kingine, mipangilio na matangazo hayahamii yenyewe.
- Kamera ya simu inahitaji HTTPS (Vercel hutoa HTTPS moja kwa moja).

# Hexatess Koda 🐝 (slovenska verzija)
[![PyPI](https://img.shields.io/pypi/v/hexatess-code)](https://pypi.org/project/hexatess-code/) 

[![Python](https://img.shields.io/pypi/pyversions/hexatess-code)](https://pypi.org/project/hexatess-code/) 

[![CI](https://github.com/lovro-abram/hexatess-code/actions/workflows/ci.yml/badge.svg)](https://github.com/lovro-abram/hexatess-code/actions/workflows/ci.yml) 

**Eksperimentalna 2D koda na šestkotni mreži** — s šestkotnim
bullseye najditeljem, spiralno serijalizacijo in prosto izbiro
Reed-Solomon popravek napak od 5 % do 90 %.

![Primer Hexatess kode](docs/img/hexatess_primer.png)

```python
from hexatess import encode, decode, render

grid, params = encode("Živjo, Hexatess!", ec_pct=30)
render(grid, "zivjo.png")
besedilo, stat = decode(grid)       # ('Živjo, Hexatess!', {...})
```

## Anatomija simbola

![Anatomija simbola](docs/img/hexatess_anatomija.png)

* **A** — prava kodirana koda: šestkotni bullseye najditelj (obroči
  0–4), orientacijski ključ (obroč 5: dve temni celici), podatkovno
  območje (obroči 6 …) v spiralnem vrstnem redu in tiho območje
  vsaj 1 modul;
* **B** — bližnjica finderja: temen center (pravilo v0.2:
  `bit = 1 − (obroč mod 2)`), izmenično temni/svetli obroči in ključ — prvi
  dve celici kanoničnega vrstnega reda obroča 5 sta temni, kar lomi
  60-kratno simetrijo in označuje smer začetka spirale;
* **C** — spiralni vrstni red bitov čez obroča 6–7 (bit 0 na celici
  `(−6, +6)`), izrisan neposredno iz izhoda referenčnega kodirnika.

## Zakaj šestkotniki?

* **+15,5 % gostote pakiranja** glede na kvadratno mrežo — šestkotniki
  zapolnijo površino s ~15,5 % več moduli pri enaki velikosti modula,
  kar neposredno pomeni več podatkov na enaki površini.
* **Rotacijska izotropija** — tri osi simetrije namesto dveh; poškodbe
  s katere koli smeri so statistično enakovredne.
* **Preverjena dediščina** — MaxiCode (UPS, ISO/IEC 16023) je že
  dokazal, da šestkotna 2D koda deluje v praksi; Hexatess Koda idejo
  posploši na spremenljivo velike, visokokapacitetne simbole v duhu
  Aztec Code.
* **Sodobno ravnanje z napakami** — zvezni proračun EC od 5 % do 90 %
  (ne 7 diskretnih ravni), neodvisni RS bloki do 50 podatkovnih bajtov
  in dvojno zaščitena glava.

> **Stanje: eksperimentalno.** Format je mlad: specifikacija simbola in
> referenčna implementacija sta trdni in temeljito preizkušeni (2.500+
> testov, konformnostni vektorji).  **Kamera-dekodirnik**
> (`hexatess.camera`, neobvezen `[camera]` dodatek) že bere simbole iz
> pravih fotografij v približno sekundi — natisnjenih nalepek,
> prosojnic, nagnjenih in zasukanih posnetkov. Od specifikacije v0.3
> se vnos samodejno zlib-stisne, zato dolga besedila
> zasedejo precej manjše simbole. Glej načrt spodaj. Posvojitev
> mladega formata je premišljena stav;
> [polna specifikacija formata](SPECIFICATION.md) je zavarovanje.

## Namestitev

```bash
pip install hexatess-code            # iz PyPI (ko bo objavljeno)
pip install "hexatess-code[camera]"  # + dekodiranje fotografij (numpy, opencv, scipy)
# ali iz izvorne kode:
pip install -e .
```

Zahteva Python ≥ 3.8; Pillow za izris, numpy + OpenCV + SciPy za
neobvezen kamera-dekodirnik.

## Ukazna vrstica

```bash
hexatess "Živijo svet" -o koda.png --ec 30
hexatess --demo                       # demo simbol + statistika odpornosti
hexatess decode-photo foto1.jpg foto2.jpg   # preberi simbole iz fotografij
```

Vnos se samodejno zlib-stisne, kadar to prihrani prostor
(`--no-compress` to izklopi; zastavica v glavi zagotavlja polno
združljivost nazaj).

## Stiskanje vsebine (spec v0.3)

En bit v glavi označi vsebino kot zlib-zaporedje. Kodirnik ga uporabi
samo, kadar res pomaga, dekodirniki pa razpenjajo prozorno — simboli
brez zastavice so bajtno identični v0.2. V praksi (EC 30, razen kjer
je navedeno):

| vsebina | surovo | shranjeno | simbol |
|---|---|---|---|
| 80 številk | 80 B | 21 B | rmax 17 → 11 |
| `"X" × 250` | 250 B | 12 B | rmax 30 → 10 |
| 849-bajtni slovenski odstavek | 849 B | 203 B | ne bi šel noter → rmax 28 |
| kratki nizi (≤ ~30 B) | — | nespremenjeno | odglava zmaga |

Največja *shranjena* kapaciteta je nespremenjena (329 bajtov pri EC 5),
zato se nestisljivi podatki obnašajo tako kot prej.

## API

| Funkcija | Opis |
|---|---|
| `encode(besedilo, ec_pct=30, mask_id="auto", min_rings=None, compress="auto")` | UTF-8 besedilo → `(mreza, parametri)`; mreža preslika aksialne `(q, r)` v `0/1` |
| `decode(mreza)` | mreža → `(besedilo, statistika)`; RS popravek in razpenjanje sta prozorna |
| `render(mreza, pot, size_px=18, ...)` | mreža → PNG (pointy-top šestkotniki, tiho območje, supersampling) |
| `sample_grid_from_image(pot, rmax, ...)` | idealno vzorčenje izrisanega PNG (pomožnik za samoteste) |
| `run_tests(...)` | statistika odpornosti na šum in lake |
| `hexatess.camera.decode_photo(pot)` | fotografija → `(besedilo, statistika)`; zaznava najditelja, korekcija perspektive, prilagodljivo vzorčenje (neobvezen `[camera]` dodatek) |

`parametri` / `statistika` vsebujeta `rmax` (radij v obročih), `mask`,
`ec`, `blocks` (seznam `(podatkovni_bajti, ecc_bajti)`), `data_len`
(shranjena dolžina) in `compressed`; `statistika` poroča še
`repair_bits` (knjiga RS popravkov), pri kameri pa `sector` in
`finder_hits`.

## Proračun za popravo napak

Izbirajte poljuben večkratnik 5 med 5 in 90:

| EC | Značaj |
|---|---|
| 5–15 | največja kapaciteta, čista okolja |
| 25–40 | splošna uporaba (privzeto 30) |
| 50–70 | industrija / zunanjost |
| 80–90 | skrajna tolerantnost na poškodbe |

Fizično obnašanje (izmerjeno na referenčni implementaciji): en obrnjen
modul je ena *simbolna* napaka RS, zato je tolerantnost na enakomeren
šum približno `EC / 16` % modulov, skupinska poškodba (madež, laka) pa
preživi večkrat večji delež površine, ker se obrati zbirajo znotraj
celih bajtov.

## Implementirajte jo v svojem jeziku

Format je namenoma **specifikacija-na-prvem-mestu**: vse, kar potrebujete
za neodvisno implementacijo, je v [`SPECIFICATION.md`](SPECIFICATION.md),
datoteka
[`test_vectors/vectors_v0.3.json`](test_vectors/vectors_v0.3.json)
pa vsebuje fiksne vhode/izhode (mreže, glave, poškodovane simbole,
pričakovane rezultate) za preverjanje skladnosti. Če vaš dekodirnik v
Rust/Go/JS prenese vektorje, govori Hexatess.

## Načrt

1. ~~v0.2/0.3 — dekodiranje s kamero~~ **končano (v0.3.0):**
   `hexatess.camera` bere simbole iz fotografij — zaznavanje najditelja,
   homografija + korekcijsko polje, prilagodljivo vzorčenje;
   preverjeno na natisnjeni prosojnici z ukrivljenostjo in odsevi.
   **v0.3.1:** ≈10× hitreje (tipična 12 MP fotografija ~1 s) ter
   stabilno vzorčenje zunanjih obročev in izbira poze, odporna na
   napačno dekodiranje.
2. ~~v0.3 — stiskanje vsebine~~ **končano (v0.3.1):** zlib zastavica v
   glavi, samodejno, kadar pomaga.
3. **Dekodiranje z izbrisi:** moduli pod madežem se razglasijo
   za izbrise → podvojena zmogljivost popravka.
4. **JavaScript/TypeScript SDK** + spletni playground (koda v brskalniku
   v 10 sekundah).
5. Večji radiji / kapaciteta nad 329 shranjenimi bajti (nezdružljiva
   sprememba glave).

Prispevki so dobrodošli — glej [CONTRIBUTING.md](CONTRIBUTING.md).

## Licenca

* Koda: [MIT](LICENSE)
* Specifikacija: CC-BY-4.0 — implementirajte kjerkoli, komercialno, pod
  katero koli licenco, brez avtorskih pravic, za vedno.

---

*Hexatess Koda stoji na ramih velikanov: Aztec Code (bullseye + spirala),
MaxiCode (šestkotna mreža), QR Code in Data Matrix (Reed-Solomon
praksa).*

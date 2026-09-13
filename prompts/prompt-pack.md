# Prompt pack — variante A (IL GRANITO)

Scritti in inglese: tutti i modelli video rendono meglio così, anche quando
l'interfaccia è in italiano.

**Struttura:** quattro inquadrature brevi da montare in sequenza. Genera un
shot alla volta. Non chiedere l'intera sequenza in una sola generazione — su
clip lunghe i modelli perdono coerenza a metà strada.

**Regola d'oro:** il blocco `[CHARACTER]` qui sotto va incollato **identico**
in ogni prompt. È quello che tiene insieme il personaggio tra uno shot e
l'altro. Cambiare anche solo una parola fa derivare il design.

---

## [CHARACTER] — blocco fisso da riusare

```
a colossal humanoid, 2.6 meters tall, barrel-chested, shoulders merging into
the neck without a break. His skin is weathered olive-green granite, matte and
porous like wet stone. His body is fractured: deep fissures run between the
muscle plates, and amber ember-light glows out from inside them, brightest
across the sternum and along the forearms, nearly dark on the legs. Grey-green
lichen sits in the deepest crevices of his shoulders. Bald, with a single
heavy protruding brow ridge. His eyes are two points of amber light with no
visible whites. His jaw is too wide for his skull, lower canines protruding.
Fine mineral dust sheds from him as he moves.
```

---

## SHOT 1 — "qualcosa non va" (3s)

*Image-to-video. Immagine di partenza: la foto frontale in `reference/`.*

```
Medium close-up on a young man, shirtless, standing in a dim concrete stairwell.
He is breathing hard. He looks down at his own forearm. The veins under his skin
darken and lift. He clenches his fist and the knuckles crack audibly. His jaw
tightens. He is frightened, not angry — he does not understand what is happening
to him.

Handheld camera, very slight drift. Cold blue-grey light from a window off-frame
left. Shallow depth of field. Photoreal, 35mm, natural film grain.
No transformation yet in this shot.
```

**Cosa controllare:** il volto deve restare identico alla foto. Se già qui
slitta, rigenera — non andare avanti.

---

## SHOT 2 — la trasformazione (4s)

*Image-to-video. Immagine di partenza: l'ultimo frame dello Shot 1.*

```
The same man, same stairwell, same framing. His skin greys and hardens, turning
to matte olive-green stone that spreads outward from the centre of his chest.
The hardened surface then cracks apart like drying clay, and amber ember-light
bleeds out from inside every fissure. He grows: his shoulders widen and rise,
his neck thickens into them, his height increases and pushes him toward the top
of the frame. His face remains clearly recognizable throughout — same bone
structure, same nose, same eye spacing — while the brow ridge thickens above it.

Camera slowly pushes in and tilts up to follow his growing height.
The amber light becomes the dominant light source in the room, warm against the
cold blue.
Photoreal, heavy practical texture, no cartoon stylization.
```

**Nota:** il "tilt up" è ciò che vende la scala. Senza movimento di camera
verso l'alto, la crescita non si legge.

---

## SHOT 3 — il reveal (3s)

```
[CHARACTER]

He stands at full height in the cramped concrete stairwell, hunched because the
ceiling is too low for him. Mineral dust drifts in the air around him. He slowly
raises his head and looks directly into the lens.

Low angle, camera near floor level looking up. Wide lens, 24mm.
Amber glow from his fissures lighting the concrete walls from below.
Held still — no camera movement. Photoreal.
```

**Perché fermo:** dopo due shot in movimento, l'immobilità colpisce. E i modelli
sbagliano meno.

---

## SHOT 4 — la vetrata (4s)

```
[CHARACTER]

He charges a full-height plate-glass window and goes straight through it. The
glass does not shatter into dust — it breaks into large jagged sheets that turn
end over end through the air, catching the amber light from his body as they
fall. He lands outside in a crouch, one fist down, on wet asphalt at night.

Camera is outside, waiting for him, slightly low. It shakes on the impact.
Slow motion at the moment of the break, then back to normal speed on the landing.
Photoreal, cinematic, night, wet reflective ground.
```

**La parte difficile è il vetro.** I modelli tendono a farlo esplodere in
polvere bianca, che sembra finta. Insistere su *large jagged sheets*, e se non
viene aggiungere: `the glass breaks in slow motion into a few big angular
shards, not into small particles.`

---

## Varianti da provare se uno shot non esce

- **Cresce male / proporzioni che ballano** → togli il movimento di camera e
  rigenera fermo. Il movimento moltiplica gli errori.
- **Il volto non è più lui** → rimetti la foto di riferimento come input anche
  sugli shot successivi, non solo sul primo.
- **Troppo "action figure" di plastica** → aggiungi `matte surface, no specular
  highlights, heavy surface texture, visible pores in the stone`.
- **Scena troppo buia** → la luce ambra deve venire *da lui*: aggiungi `he is
  the primary light source in the scene`.

---

## Ordine di lavoro

Fai prima lo **Shot 3** (il reveal, fermo). È il più facile e ti dice subito se
il design regge. Se il colosso funziona lì, passa al 2 (il più difficile), poi
1 e 4.

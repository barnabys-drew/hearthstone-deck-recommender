# Deck JSON examples

## Offline smoke test by DBF ID

```json
{
  "name": "Deckstring Smoke Test",
  "class": "Warrior",
  "format": "wild",
  "hero_dbf_id": 7,
  "cards": [
    {"dbfId": 1, "count": 2},
    {"dbfId": 2, "count": 2},
    {"dbfId": 3, "count": 2},
    {"dbfId": 4, "count": 1}
  ]
}
```

Run with `--deck-size none --no-fetch`; the expected current deckstrings-library code is `AAEBAQcBBAMBAgMAAA==`.

## Sideboard structure

Use `sideboard_cards` when a main-deck card owns extra cards, such as E.T.C., Band Manager. Supply owner by name or `owner_dbf_id`.

```json
{
  "name": "ETC Example",
  "class": "Warrior",
  "format": "wild",
  "cards": [
    {"name": "E.T.C., Band Manager", "count": 1}
  ],
  "sideboard_cards": [
    {"name": "Brawl", "count": 1, "owner": "E.T.C., Band Manager"}
  ]
}
```

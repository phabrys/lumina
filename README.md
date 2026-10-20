# Lumina

Intégration Home Assistant de gestion automatique des lumières et ventilateurs **par pièce**, avec prise en compte de la présence, de la luminosité et de la température.

Chaque pièce est une entrée de configuration indépendante, ajoutée depuis l'interface : aucune automatisation à écrire ou à dupliquer.

## Fonctionnement

```mermaid
stateDiagram-v2
    [*] --> Vide
    Vide --> Occupée : présence détectée
    Occupée --> Vide : plus de présence\n(extinction après délai)
    Occupée --> Manuel : action à la main\nsur une lumière/un ventilateur
    Vide --> Manuel : action à la main
    Manuel --> Occupée : fin du délai\n(pièce occupée)
    Manuel --> Vide : pièce vide\nou fin du délai
```

- **Présence** : la pièce n'est considérée vide qu'après un court délai sans détection (30 s par défaut). Une micro-coupure du détecteur n'éteint donc rien et ne lève pas le contrôle manuel. Les délais d'extinction restent comptés depuis la fin réelle de présence.
- **Lumières** : allumées à l'arrivée si la luminosité est sous le seuil (toujours, s'il n'y a pas de capteur de luminosité). Si le capteur choisi ne répond pas, Lumina se fie au soleil (`sun.sun`) : allumage seulement s'il est couché. Éteintes quand la pièce est vide depuis le délai réglé.
- **Ventilateurs** : allumés quand la pièce est occupée et que la température atteint le seuil, arrêtés 1 °C en dessous (hystérésis), avec au moins 5 min entre deux bascules dues à la température. Sans capteur de température, ils suivent simplement la présence.
- **Contrôle manuel** : allumer ou éteindre une lumière ou un ventilateur à la main suspend l'automatisme de ce groupe pendant la durée réglée. Plusieurs changements en moins de 5 s (deux lampes, extinction + vitesse) comptent pour un seul geste. La reprise manuelle est levée dès que la pièce est confirmée vide.

### Mode nuit

Chaque pièce a sa propre plage de nuit (22 h → 7 h par défaut) avec ses réglages dédiés :

- **Luminosité des lumières** : 30 % la nuit, 100 % le jour par défaut. À **0 %**, les lumières ne s'allument plus automatiquement la nuit (pratique dans une chambre d'enfants).
- **Délais d'extinction** propres à la nuit. Celui des ventilateurs est long par défaut (30 min), car un détecteur PIR ne voit pas une personne endormie immobile.
- **Seuil de température** de nuit (26 °C par défaut).

Mettre la même heure en début et en fin de nuit désactive le mode nuit pour la pièce. La période en cours (jour/nuit) apparaît en attribut du capteur d'état.

Le switch **Nuit maintenant** force le mode nuit tout de suite ; il se désactive seul à la prochaine heure de fin de nuit, même si la pièce n'a pas de plage de nuit.

### Confort

- **Maintien de présence** : une TV, une enceinte ou une clim active garde la pièce occupée quand les détecteurs ne voient plus personne (devant la TV sans bouger, par exemple). Le maintien prolonge une présence, il ne la déclenche pas. Une pièce occupée le reste après un redémarrage de Home Assistant tant que le maintien est actif : l'occupation d'avant le redémarrage est reprise, puis levée après la confirmation d'absence si plus rien ne la justifie.
- **Température ressentie** : avec un capteur d'humidité, les ventilateurs suivent l'indice de chaleur (NOAA) plutôt que la température mesurée. 27 °C à 85 % d'humidité se ressentent comme 30 °C.
- **Vitesse progressive** : les ventilateurs démarrent à la vitesse minimale (33 %) au seuil, puis montent jusqu'à 100 % sur l'écart réglé (3 °C). Une vitesse minimale à 0 revient au simple marche/arrêt. Changer la vitesse à la main compte comme une reprise manuelle.
- **Avertissement avant extinction** : les lumières baissent à 20 % pendant 15 s avant de s'éteindre. Un mouvement pendant ce temps rétablit la lumière.
- **Teinte** : 4000 K le jour, 2700 K la nuit, pour les lumières à blanc réglable (0 = ne pas modifier).
- **Journal** : chaque décision apparaît dans le Journal avec sa raison, dans la langue de Home Assistant (français ou anglais), par exemple « allume les lumières à 30 % (nuit, 12 lx) ». Les ajustements de vitesse fréquents sont regroupés (une entrée toutes les 10 min au plus).
- **Lumière du jour** : avec un seuil d'extinction réglé, les lumières s'éteignent quand le capteur mesure au moins cette valeur pendant 5 min. Règle-le **au-dessus** de ce que mesure le capteur lampes allumées, sinon la lampe s'éteindrait d'elle-même. Après une telle extinction, l'allumage automatique ne reprend qu'après 10 min sous le seuil d'allumage, ou quand la pièce se vide.
- **Plusieurs lumières ou ventilateurs** : par défaut, Lumina allume toutes les lumières (ou tous les ventilateurs) éteints de la pièce ; l'option « Seulement si aucune n'est allumée » (« aucun » pour les ventilateurs) respecte un appareil déjà allumé.

Les lumières et ventilateurs peuvent aussi être des prises (`switch`), par exemple un ventilateur branché sur une prise Zigbee.

## Entités créées par pièce

| Entité | Rôle |
|---|---|
| `sensor.<pièce>_lumina_etat_de_la_piece` | Occupée / Vide / Contrôle manuel |
| `switch.…_gestion_auto_des_lumieres` | Active ou suspend l'automatisme des lumières |
| `switch.…_gestion_auto_des_ventilateurs` | Active ou suspend l'automatisme des ventilateurs |
| `number.…_seuil_de_luminosite` | Seuil en lx (défaut 50) |
| `number.…_seuil_de_temperature` | Seuil en °C (défaut 27) |
| `number.…_delai_d_extinction_des_lumieres` | En secondes (défaut 120) |
| `number.…_delai_d_arret_des_ventilateurs` | En secondes (défaut 300) |
| `number.…_duree_du_controle_manuel` | En minutes (défaut 30, 0 pour désactiver) |
| `number.…_confirmation_d_absence` | En secondes (défaut 30, 0 = immédiat) |
| `number.…_luminosite_des_lumieres_jour` | En % (défaut 100) |
| `time.…_debut_de_la_nuit` / `time.…_fin_de_la_nuit` | Plage de nuit (défaut 22:00 → 07:00) |
| `number.…_luminosite_des_lumieres_nuit` | En % (défaut 30, 0 = pas d'allumage la nuit) |
| `number.…_delai_d_extinction_des_lumieres_nuit` | En secondes (défaut 60) |
| `number.…_delai_d_arret_des_ventilateurs_nuit` | En secondes (défaut 1800) |
| `number.…_seuil_de_temperature_nuit` | En °C (défaut 26) |
| `switch.…_nuit_maintenant` | Force le mode nuit jusqu'à la fin de la prochaine nuit |
| `sensor.…_temperature_ressentie` | Indice de chaleur (si un capteur d'humidité est choisi) |
| `number.…_vitesse_minimale_des_ventilateurs` | En % (défaut 33, 0 = marche/arrêt) |
| `number.…_ecart_pour_la_vitesse_maximale` | En °C (défaut 3) |
| `number.…_avertissement_avant_extinction` | En secondes (défaut 15, 0 = extinction directe) |
| `number.…_teinte_des_lumieres_jour` / `…_nuit` | En K (défaut 4000 / 2700, 0 = ne pas modifier) |
| `number.…_extinction_a_la_lumiere_du_jour` | En lx (défaut 0 = désactivé) |
| `select.…_lumieres_a_allumer` | Toutes / Seulement si aucune n'est allumée |
| `select.…_ventilateurs_a_allumer` | Tous / Seulement si aucun n'est allumé |
| `button.…_reprendre_l_automatisme` | Met fin au contrôle manuel tout de suite |

Les réglages n'apparaissent que s'ils ont un sens pour la pièce (pas de seuil de luminosité sans capteur, etc.) et sont conservés au redémarrage.

## Carte

[Lumina Card](https://github.com/phabrys/lumina-card) affiche et pilote une pièce Lumina dans un tableau de bord.

## Installation

### Via HACS (recommandé)

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajouter `https://github.com/phabrys/lumina`, catégorie **Intégration**.
3. Installer **Lumina**, puis redémarrer Home Assistant.

### Manuelle

Copier `custom_components/lumina` dans le dossier `custom_components` de la configuration Home Assistant, puis redémarrer.

## Ajouter une pièce

**Paramètres → Appareils et services → Ajouter une intégration → Lumina**, puis choisir la pièce. Les capteurs de présence, lumières, ventilateurs et capteurs de luminosité/température rattachés à la pièce sont proposés automatiquement. Les entités se modifient ensuite via **Configurer**.

Pour que la détection automatique fonctionne, chaque entité (ou son appareil) doit être rattachée à la bonne pièce dans Home Assistant.

## Diagnostic

**Paramètres → Appareils et services → Lumina → ⋮ → Télécharger les diagnostics** fournit un fichier JSON avec la configuration de la pièce, les réglages, l'état interne et l'état des entités suivies.

## Versions

Les versions sont publiées automatiquement : quand la CI réussit sur `main` avec un nouveau numéro de version dans `manifest.json`, le tag et la release GitHub sont créés à partir du `CHANGELOG.md`, et HACS propose la mise à jour. Une CI en échec ne publie rien.

## Développement

```bash
pip install -r requirements_test.txt
pytest
```

## Licence

Distribué sous licence MIT. Voir [LICENSE](LICENSE).

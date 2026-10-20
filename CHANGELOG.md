# Changelog

## 0.5.1 — 2026-10-20

- Ventilateurs : à la fin du cycle minimal, la bascule en attente s'applique sans recalcul du temps restant.
- Les releases ne sont plus publiées qu'après des tests au vert.

## 0.5.0 — 2026-10-20

Corrections issues de l'observation du Journal en conditions réelles.

- Absence confirmée après un délai réglable (30 s par défaut) : les micro-coupures des détecteurs ne vident plus la pièce et ne lèvent plus le contrôle manuel. Les délais d'extinction restent comptés depuis la fin réelle de présence.
- Capteur de luminosité indisponible : repli sur la position du soleil au lieu de considérer la pièce sombre.
- Ventilateurs : au moins 5 min entre deux bascules marche/arrêt dues à la température.
- Changements rapprochés d'un même groupe (moins de 5 s) : une seule reprise manuelle.

## 0.4.0 — 2026-10-18

- Extinction des lumières quand la lumière naturelle suffit, avec verrou anti-oscillation.
- Choix du comportement avec plusieurs lumières : toutes, ou seulement si aucune n'est allumée.
- Journal moins bavard : ajustements de vitesse regroupés, réajustement seulement au-delà de 10 points.
- « Nuit maintenant » s'arrête à la prochaine heure de fin de nuit, même sans plage de nuit.
- Diagnostics téléchargeables depuis la page de l'intégration.
- Migration versionnée de la configuration (1.1 → 1.2).

## 0.3.0

- Maintien de présence (TV, enceinte, clim…).
- Température ressentie avec un capteur d'humidité.
- Vitesse des ventilateurs proportionnelle à la chaleur.
- Avertissement avant extinction, teinte jour/nuit, Journal explicatif.
- Interrupteur « Nuit maintenant ».

## 0.2.0

- Mode nuit par pièce : plage horaire, luminosité, délais et seuil de température dédiés.

## 0.1.0

- Première version : une entrée par pièce, présence, luminosité, température, reprise manuelle.

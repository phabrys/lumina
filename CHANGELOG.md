# Changelog

## 0.9.0 — 2026-10-20

- Avertissement avant extinction : quelqu'un qui revient pendant que les lumières baissent retrouve la luminosité d'avant, et non celle du réglage. La nuit, avec l'allumage automatique coupé, une lampe allumée à la main ne revient plus à 1 %. Seules les lumières baissées sont rétablies.
- Détecteur de présence indisponible (redémarrage de Zigbee2MQTT, de ZHA…) : la pièce reste occupée au lieu de se vider et de tout éteindre. Même chose au démarrage de Home Assistant.
- Contrôle manuel : un appareil lent (cloud, clim) qui confirme une commande de Lumina jusqu'à 1 min plus tard, sous un autre contexte, ne déclenche plus de contrôle manuel. La vitesse confirmée peut être arrondie au cran du ventilateur.
- Ventilateurs : pendant le cycle minimal de 5 min, la vitesse des ventilateurs en marche suit la température.
- Clims : une clim en simple ventilation (`fan_only`) n'est plus éteinte ni modifiée quand la pièce se vide.
- Journal : un message absent d'une traduction s'affiche en anglais au lieu de provoquer une erreur.
- Appareil : la version de Lumina apparaît sur la fiche de l'appareil.
- Code : contrôleur découpé (socle commun, clims, lumière du jour), constantes de Home Assistant à la place des textes en dur ; ruff et mypy dans la CI ; tests contre la version actuelle et la version minimale de Home Assistant (2025.6.0).

## 0.8.0 — 2026-10-20

- Clims : nouvelles entités de pièce. Lumina ne les allume jamais ; quand la pièce est vide depuis le délai réglé (15 min), il les éteint, les passe en eco ou relève leur consigne de 2 °C (réglable le jour et la nuit ; rien la nuit par défaut), puis rétablit leur état si quelqu'un revient dans les 2 h.
- Ventilateurs pendant la clim : selon la température (comme avant), en brassage à vitesse fixe, ou arrêtés.
- Nuit : un geste manuel tient jusqu'à la fin de la nuit au lieu de la durée réglée. Une lumière éteinte au coucher ne se rallume plus au bout de 30 min. Désactivable avec le switch « Contrôle manuel jusqu'au matin ».

## 0.7.1 — 2026-10-20

- Maintien de présence : une pièce occupée le reste après un redémarrage de Home Assistant si un média (TV, enceinte…) joue toujours, même s'il met quelques secondes à redevenir disponible. Un média qui joue dans une pièce vide ne l'occupe toujours pas.

## 0.7.0 — 2026-10-20

- Ventilateurs : nouveau réglage « Ventilateurs à allumer », comme pour les lumières. Par défaut, tous les ventilateurs éteints démarrent, même si l'un tourne déjà (avant, Lumina ne touchait à rien) ; l'option « Seulement si aucun n'est allumé » rétablit l'ancien comportement.
- Journal : les messages suivent la langue de Home Assistant (français ou anglais).
- Journal : plus d'entrée d'échec au nom d'une pièce déchargée ou rechargée entre-temps.

## 0.6.1 — 2026-10-20

- Journal : un appel qui échoue côté appareil (script introuvable, entité muette…) est signalé au lieu de passer inaperçu.
- Les tests tournent sous Python 3.14, contre la version actuelle de Home Assistant.

## 0.6.0 — 2026-10-20

Préparation de la carte [Lumina Card](https://github.com/phabrys/lumina-card).

- Le capteur d'état expose les entités de la pièce (lumières, ventilateurs, capteurs, maintien) et les échéances (`lights_off_at`, `fans_off_at`, `vacancy_at`).
- Nouveau bouton « Reprendre l'automatisme » : met fin au contrôle manuel tout de suite.

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

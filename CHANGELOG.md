# Changelog

## 0.12.0 — 2026-10-25

Corrections et réglages tirés des nuits du 23 au 25 octobre.

- Fin de nuit : un geste tenu jusqu'au réveil (ventilateur éteint à la main au coucher) prend fin avec le réveil, et non une fraction de seconde avant. Lumina ne réapplique plus le sommeil à cet instant : le ventilateur éteint à la main ne se rallume plus à pleine vitesse à l'heure du réveil.
- Nouveau champ facultatif dans **Configurer**, **Détecteurs qui voient une personne immobile** (radar mmWave, comme l'Aqara FP2), choisis parmi les capteurs de présence. Tant que l'un d'eux répond, Lumina ne présume plus de dormeur caché : une chambre qu'il voit vide la nuit l'est vraiment (ventilateurs et clim suivent les délais de nuit), le répit du réveil ne commence que si quelqu'un est là et prend fin quand la pièce se vide. Sans ce champ, rien ne change.
- Entité de sommeil : un passage à « on » alors que personne n'est dans la pièce (téléphone posé immobile ailleurs) n'endort plus la pièce, et le Journal le dit. Avec un détecteur qui voit l'immobilité, il doit voir quelqu'un ; sinon, quelqu'un doit avoir été détecté depuis moins de 30 min.
- Réveil par l'entité de sommeil : même répit qu'à la fin de nuit. La lumière ne s'allume plus dès que le téléphone bouge : elle attend un geste ou la fin de la durée du contrôle manuel.
- Détecteurs de présence tous muets (piles mortes…) : Lumina n'éteint plus lumières, ventilateurs ni clims parce que la pièce semble vide, même quand la panne date d'avant le démarrage ou survient pendant la confirmation d'absence. Un détecteur muet depuis plus d'une heure est signalé dans les Réparations de Home Assistant, et le signalement disparaît quand il répond de nouveau.
- Capteur d'état : nouveaux attributs `presence_still_sensors`, `presence_unavailable` (détecteurs muets) et `presence_unknown` (aucun détecteur ne répond).

## 0.11.0 — 2026-10-24

- Fin de nuit selon le jour : deux nouveaux champs facultatifs dans **Configurer**, **Jours travaillés** (capteur de l'intégration Workday) et **Calendriers de vacances**. Un jour de repos (week-end, férié), la nuit se termine à la nouvelle heure **Fin de la nuit (repos)** ; un jour où un calendrier de vacances a un événement, à la **Fin de la nuit (vacances)** ; les autres jours, à la **Fin de la nuit**. Le sommeil, la nuit forcée et la plage de nuit suivent l'heure du matin concerné. Chaque nouvelle heure n'existe que si sa source est choisie : sans elles, rien ne change.
- Capteur d'état : nouveaux attributs `night_end_at` (prochaine fin de nuit), `night_end_day_kind` (`workday`, `day_off` ou `holidays`), `workday_entity` et `holiday_calendars`.

## 0.10.4 — 2026-10-22

- Réglage « Extinction à la main la nuit » : choix raccourcis en « Durée réglée », « Jusqu'au départ (sommeil) » et « Jusqu'au réveil (sommeil) », comme dans Lumina Card 0.3.6. Le comportement et les valeurs du select ne changent pas.

## 0.10.3 — 2026-10-22

- Réglages « Lumières à allumer » et « Ventilateurs à allumer » renommés « Si une lumière est déjà allumée » et « Si un ventilateur tourne déjà », avec les choix « Allumer les autres » ou « Ne rien toucher ». Le comportement ne change pas. Les pièces existantes gardent leur `entity_id` (`select.…_lumieres_a_allumer`, `select.…_ventilateurs_a_allumer`) ; les nouvelles reçoivent `select.…_si_une_lumiere_est_deja_allumee` et `select.…_si_un_ventilateur_tourne_deja`.

## 0.10.2 — 2026-10-21

Pendant le sommeil, rien ne s'allume ni ne s'arrête sur un dormeur.

- Sommeil : ni ventilateur ni clim ne s'arrêtent parce que la pièce semble vide, même quand le sommeil commence alors que le dormeur n'est déjà plus vu par le détecteur (téléphone mis en charge, switch Sommeil activé au lit). Avant, ils s'arrêtaient après le délai de nuit, et la clim pouvait être éteinte ou passée en eco.
- Réveil de fin de nuit : pendant la durée du contrôle manuel (30 min), sauf geste sur la lumière, le dormeur reste présumé là : la lumière reste éteinte, et ventilateur et clim continuent au lieu de s'arrêter tout de suite. Une pièce qui semble vide ne lève plus ce répit : un dormeur vu à 7 h puis immobile 30 s rallumait la lumière à son mouvement suivant. Sans signe de vie au bout du délai, ventilateur et clim s'arrêtent aussitôt.
- Redémarrage de Home Assistant à cheval sur la fin de nuit : le réveil est repris, la lumière ne s'allume plus sur le dormeur. Comme sans redémarrage, un sommeil deviné au salon n'a pas de répit.
- Avertissement avant extinction pendant le sommeil : un mouvement rend aux lampes leur luminosité d'avant, mais une lampe dont la luminosité était inconnue reste baissée au lieu de passer à 100 %.
- Capteur d'état : l'attribut `lights_held_until` (0.10.1) devient `wake_hold_until`.
- Code : sommeil regroupé dans `sleep.py` (`start_sleep`, `wake`), règle « ne pas arrêter pendant le sommeil » en un seul endroit, raisons de réveil en constantes ; tests du sommeil dans `tests/test_sleep.py`, aides communes dans `tests/common.py`.

## 0.10.1 — 2026-10-21

- Réveil de fin de nuit : la lumière reste aussi éteinte pour un dormeur que le détecteur ne voyait plus. Ce maintien dure au plus la durée du contrôle manuel (30 min), pour qui reviendrait dans une pièce vidée avant le réveil.
- Veilleuse : éteindre la lumière au coucher (à la main ou par un script) ne l'empêche plus de s'allumer pendant la nuit. Éteindre la veilleuse elle-même à la main la garde éteinte jusqu'au réveil.
- Heure de fin de nuit avancée à une heure déjà passée : le sommeil et « Nuit maintenant » prennent fin tout de suite au lieu de durer jusqu'au lendemain.
- Redémarrage pendant le sommeil : un appareil allumé à la main garde sa durée réglée au lieu de passer « jusqu'au réveil ».
- Capteur d'état : nouvel attribut `lights_held_until`.

## 0.10.0 — 2026-10-21

- Sommeil : nouvel état de la pièce, distinct de la nuit éveillée. Une pièce en sommeil n'allume pas les lumières (sauf veilleuse, nouveau réglage « Luminosité en sommeil », 0 % par défaut), garde les gestes manuels jusqu'au réveil et, dès que quelqu'un y a été détecté depuis le coucher, est présumée occupée : un dormeur que le détecteur ne voit plus n'arrête plus les ventilateurs ni la clim, et les ventilateurs suivent toujours la température.
- Sommeil : on y entre avec le switch « Sommeil » (à toute heure, sieste comprise), avec une entité de sommeil choisie dans Configurer (capteur de lit, téléphone en charge…), ou la nuit en éteignant toutes les lumières à la main. On en sort avec le switch, l'entité, et toujours à l'heure de fin de nuit.
- Lumières éteintes à la main la nuit : le switch « Contrôle manuel jusqu'au matin » est remplacé par le select « Extinction à la main la nuit » : contrôle manuel, sommeil jusqu'à ce que la pièce se vide (salon, par défaut pour une nouvelle pièce), ou sommeil jusqu'au réveil avec la pièce présumée occupée (chambre). Le switch actif devient « jusqu'au réveil », inactif « contrôle manuel ». Une extinction par une automatisation ou un script n'endort pas la pièce.
- Réveil de fin de nuit : la lumière reste éteinte tant que la pièce ne s'est pas vidée ; les ventilateurs d'une pièce vide depuis longtemps s'arrêtent sans attendre un nouveau délai complet. Changer l'heure de fin de nuit déplace le réveil (et la fin de « Nuit maintenant »).
- Entité de sommeil : seul un passage à « on » endort la pièce ; une entité restée « on » après le réveil du matin ne la rendort pas au redémarrage.
- Avertissement avant extinction : une lumière faible (veilleuse, nuit sous 20 %) baisse à la moitié de sa luminosité au lieu de remonter à 20 % ; presque éteinte, elle s'éteint directement.
- Contrôle manuel : une vitesse de ventilateur réglée à la main avant le coucher ou pendant le sommeil tient jusqu'au réveil, même quand le détecteur perd le dormeur. L'entrée du Journal est écrite une fois le geste terminé : deux lampes éteintes au coucher n'annoncent plus « pendant 30 min » avant le sommeil.
- Hors sommeil, un geste manuel la nuit garde la durée réglée : éteindre un ventilateur ou régler la clim sans éteindre les lumières ne tient plus jusqu'au matin.
- Capteur d'état : nouvelle valeur « En sommeil », prioritaire sur « Contrôle manuel ». Nouveaux attributs `sleeping`, `sleeping_until`, `sleep_source`, `presumed_occupied`, `sleep_entity` et `overrides_until_wake` (`overrides_until_morning` reste publié pour Lumina Card 0.2).

## 0.9.2 — 2026-10-21

- Contrôle manuel : un contrôle manuel en cours (durée réglée ou jusqu'au matin) est repris après un redémarrage de Home Assistant. La lumière éteinte au coucher ne se rallume plus quand Home Assistant redémarre la nuit (mise à jour, coupure…). Une échéance déjà passée n'est pas reprise.

## 0.9.1 — 2026-10-21

- Nuit : un contrôle manuel « jusqu'au matin » n'est plus levé quand la pièce se vide si tout le groupe est éteint. Un dormeur que le détecteur ne voit plus (FP2, PIR) ne rallume donc plus la lumière à son prochain mouvement. Un groupe resté allumé est toujours repris pour être éteint.
- Nuit : une lumière ou un ventilateur allumé à la main garde la durée réglée (30 min) au lieu de tenir jusqu'au matin. Une lumière allumée dans une pièce vide ne reste plus allumée toute la nuit.
- Avertissement avant extinction : les lumières sans variateur s'éteignent directement au lieu d'attendre 15 s sans rien baisser.

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

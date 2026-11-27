# Champs des formulaires : relecture

Fichier `formulaires_champs.json` du 2026-11-27 (à relire par Safouen (libellés pdf_image et traductions)). Les textes marqués « image : à relire » ont été recopiés depuis l'image du PDF : à comparer au formulaire papier.

## demande_acquisition

| Champ | Section | Catégorie | Préremplissage | Libellé fr | Libellé ar |
|---|---|---|---|---|---|
| `nom_prenom` | identification | contact (page seulement) | — | Nom & Prénom — texte du PDF ✔ | الاسم واللقب — **image : à relire** |
| `cin_numero` | identification | **jamais enregistré** | — | Carte d’identité nationale n° — texte du PDF ✔ | رقم بطاقة التعريف — **image : à relire** |
| `cin_date` | identification | **jamais enregistré** | — | daté du — texte du PDF ✔ | المؤرخة في — **image : à relire** |
| `raison_sociale` | identification | contact (page seulement) | — | Raison Social (société) — texte du PDF ✔ | الاسم الجماعي (للشركة) — **image : à relire** |
| `forme_juridique` | identification | contact (page seulement) | — | Forme Juridique — texte du PDF ✔ | الشكل القانوني — **image : à relire** |
| `registre_commerce` | identification | contact (page seulement) | — | Registre de Commerce n° — texte du PDF ✔ | السجل التجاري : الرقم — **image : à relire** |
| `taux_participation_tunisienne` | identification | contact (page seulement) | — | Taux de participation tunisienne — texte du PDF ✔ | نسبة المساهمة — **image : à relire** |
| `taux_participation_non_residente` | identification | contact (page seulement) | — | Taux de participation non résidente — texte du PDF ✔ | الاجنبية — **image : à relire** |
| `nationalite` | identification | contact (page seulement) | — | Nationalité — texte du PDF ✔ | الجنسية — **image : à relire** |
| `passeport_numero` | identification | **jamais enregistré** | — | Passeport (étrangers) n° — texte du PDF ✔ | رقم جواز السفر — **image : à relire** |
| `adresse` | identification | contact (page seulement) | — | Adresse — texte du PDF ✔ | العنوان — **image : à relire** |
| `email` | identification | contact (page seulement) | — | Adresse électronique — texte du PDF ✔ | العنوان الالكتروني — **image : à relire** |
| `telephone` | identification | contact (page seulement) | — | Téléphone — texte du PDF ✔ | الهاتف — **image : à relire** |
| `fax` | identification | contact (page seulement) | — | Fax — texte du PDF ✔ | الفاكس — **image : à relire** |
| `code_postal` | identification | contact (page seulement) | — | Code postal (seulement sur la version arabe) — traduction | الترقيم البريدي — **image : à relire** |
| `activite` | nature_projet | projet (chat ou page) | projet.activite | Activité — texte du PDF ✔ | طبيعة النشاط — **image : à relire** |
| `nature` | nature_projet | projet (chat ou page) | — | NATURE — texte du PDF ✔<br>Création / Extension / Transfert | نوعيته — **image : à relire**<br>احداث / توسيع / تحويل |
| `regime` | nature_projet | projet (chat ou page) | — | REGIME — texte du PDF ✔<br>Local / Totalement Exportateur / Partiellement Exportateur | النظام — **image : à relire**<br>محلي / مصدر كليا / مصدر جزئيا |
| `nombre_emplois` | nature_projet | projet (chat ou page) | projet.nombre_emplois | Nombre d’emploi à créer — texte du PDF ✔ | عدد مواطن الشغل — **image : à relire** |
| `lieu_implantation` | besoins | projet (chat ou page) | lot.zone_nom, projet.gouvernorat | Lieu D’implantation souhaité — texte du PDF ✔ | مكان الانتصاب المطلوب — **image : à relire** |
| `superficie_demandee` | besoins | projet (chat ou page) | lot.surface_m2, projet.surface_souhaitee_m2 | Superficie demandée — texte du PDF ✔ | مساحة قطعة الارض المطلوبة — **image : à relire** |
| `superficie_construite` | besoins | projet (chat ou page) | — | Superficie construite projetée (1) — texte du PDF ✔ | المساحة المبنية (1) — **image : à relire** |
| `superficie_phase1` | besoins | projet (chat ou page) | — | en 1er phase (30%) — texte du PDF ✔ | في مرحلة أولي ((30%)) — **image : à relire** |
| `superficie_phase2` | besoins | projet (chat ou page) | — | En 2eme phase (20%) — texte du PDF ✔ | في مرحلة ثانية ((20%)) — **image : à relire** |
| `puissance_kva` | besoins | projet (chat ou page) | — | Puissance installée en KVA ((Norme AFI =100 Kva/Ha)) — texte du PDF ✔ | التزود بالطاقة الكهربائية بحساب KVA ((توفر الوكالة KVA 100/ هكتار)) — **image : à relire** |
| `consommation_eau` | besoins | projet (chat ou page) | — | Consommation moyenne journalière en m3 ((Norme AFI= 40m3/jours/Ha)) — texte du PDF ✔ | التزواد بالماء الصالح للشراب : معدل استهلاك اليومي بحساب المتر المربع المكعب ((توفر الوكالة40 م3 في اليوم للهكتار الواحد)) — **image : à relire** |
| `declaration_nature` | declaration | projet (chat ou page) | — | Nature — texte du PDF ✔ | نوعيته — **image : à relire** |
| `declaration_numero` | declaration | projet (chat ou page) | — | Numéro — texte du PDF ✔ | الرقم — **image : à relire** |
| `declaration_date` | declaration | projet (chat ou page) | — | Date (seulement sur la version arabe) — traduction | التاريخ — **image : à relire** |
| `investissement` | investissement | projet (chat ou page) | projet.investissement_dt | INVISTISSEMENT (DT) — texte du PDF ✔ | حجم الاستثمار (د.ت) — **image : à relire** |
| `fonds_propres` | financement | projet (chat ou page) | — | Fond Propre (montant) — texte du PDF ✔ | تمويل ذاتي (المبلغ) — **image : à relire** |
| `credit_bancaire` | financement | projet (chat ou page) | — | Crédit bancaire (montant) — texte du PDF ✔ | قرض بنكي (المبلغ) — **image : à relire** |
| `financement_autres` | financement | projet (chat ou page) | — | Autres (montant) — texte du PDF ✔ | او مصادر اخرى (المبلغ) — **image : à relire** |
| `residus_solides` | environnement_residus | projet (chat ou page) | — | Résidus solides — texte du PDF ✔ | صلبة — **image : à relire** |
| `residus_liquides` | environnement_residus | projet (chat ou page) | — | Résidus Liquides — texte du PDF ✔ | سائلة — **image : à relire** |
| `residus_gazeux` | environnement_residus | projet (chat ou page) | — | Resideux Gazeux — texte du PDF ✔ | غازية — **image : à relire** |
| `eaux_residuelles` | environnement_eaux | projet (chat ou page) | — | Caractéristiques des eaux résiduelles — texte du PDF ✔ | خصائص بقايا المياه — **image : à relire** |
| `traitement_avant_rejet` | environnement_eaux | projet (chat ou page) | — | Caractéristiques des traitements avant rejet — texte du PDF ✔ | طرق تصرف المياه قبل تصرفها — **image : à relire** |
| `type_extincteurs` | environnement_incendie | projet (chat ou page) | — | Type d’extincteurs — texte du PDF ✔ | نوع مطفئ الحريق — **image : à relire** |
| `nombre_extincteurs` | environnement_incendie | projet (chat ou page) | — | Nombre — texte du PDF ✔ | العدد — **image : à relire** |
| `fait_a` | signature | projet (chat ou page) | — | Fait à — texte du PDF ✔ | حرر بـ — **image : à relire** |
| `date_signature` | signature | projet (chat ou page) | — | Le — texte du PDF ✔ | في — **image : à relire** |
| `signature_promoteur` | signature | **jamais enregistré** | — | Le promoteur — texte du PDF ✔ | امضاء الباعث — **image : à relire** |

Mentions imprimées :

- [fr, besoins] (1) D’une façon générale la superficie construite su sol (COS) doit être comprise entre un minium de 30% et un maximum de 50% de la sufrace du terrain — texte du PDF ✔
- [fr, besoins] La superficie du rez de chaussée et des étages réunis (CUF) ne doit pas dépasser 1,5 de la surface du terrain — texte du PDF ✔
- [fr, besoins] * Les retraits exigés : 10métres sur la (Les) façades (s) et de 5mtres à parti des clôtures séparatives avec les voisins — texte du PDF ✔
- [fr, besoins] Toutesfois, il y a lieu de conformer au cahiers des charges spécifiques de la zone industrielle d’implantation — texte du PDF ✔
- [fr, signature] Important : Le promoteur est tenu de confirmer sa demande au bout de 6 mois à dater de la présente — texte du PDF ✔
- [fr, signature] REMARQUE : La présente fiche sera remise à l’AFI dûment remplie accompagnée d’une copie de la carte d’identité — texte du PDF ✔
- [ar, besoins] (1) بصفة عامة يكون استغلال الارض المقتناة كالاتي : — **image : à relire**
- [ar, besoins] لا يجب ان تتعدى المساحة المبنية (COS) من مساحة قطعة الارض وان لا تقل عن 30% — **image : à relire**
- [ar, besoins] لا يجب ان تتعدى المساحة المبنية ( الطوابق العلوي والطوابق مجتمعة (CUF) مرة ونصف من مساحة الارض الجملية — **image : à relire**
- [ar, besoins] الارتفاع على الطوابق (retrait) : 10 امتار من الواجهة و5 امتار من السياج الفاصل للأجوار — **image : à relire**
- [ar, besoins] الا ان المشتري مطالب باحترام كراس الشروط الخاصة بالمنطقة الصناعية التي سنجز بها المشروع — **image : à relire**
- [ar, signature] هام : يتوجب على الباعث تأكيد طلبه في أجل ستة أشهر من تاريخ هذا الطلب — **image : à relire**
- [ar, signature] ملاحظة : تسلم هذه الوثيقة الى الوكالة مستوفاة البيانات ومرفوقة بنسخة من بطاقة التعريف الوطنية — **image : à relire**

## demande_service_administratif

| Champ | Section | Catégorie | Préremplissage | Libellé fr | Libellé ar |
|---|---|---|---|---|---|
| `nom_ou_raison_sociale` | demandeur | contact (page seulement) | — | Nom et prénom / raison sociale — traduction | الإسم واللقب / الإسم الإجتماعي — texte du PDF ✔ |
| `adresse_ou_siege` | demandeur | contact (page seulement) | — | Adresse / siège social — traduction | العنوان / المقر الإجتماعي — texte du PDF ✔ |
| `cin_numero` | demandeur | **jamais enregistré** | — | N° de la carte d’identité nationale — traduction | ب. ت. و. رقم — texte du PDF ✔ |
| `email` | demandeur | contact (page seulement) | — | Adresse électronique — traduction | العنوان الإلكتروني — texte du PDF ✔ |
| `telephone` | demandeur | contact (page seulement) | — | Téléphone fixe / mobile — traduction | الهاتف القار / الجوّال — texte du PDF ✔ |
| `objet_demande` | demandeur | projet (chat ou page) | — | Objet de la demande du document — traduction | الغاية من طلب الوثيقة — texte du PDF ✔ |
| `date_demande` | demandeur | projet (chat ou page) | — | Date de la demande — traduction | تاريخ المطلب — texte du PDF ✔ |
| `signature_demandeur` | demandeur | **jamais enregistré** | — | Signature du demandeur — traduction | إمضاء طالب الخدمة — texte du PDF ✔ |
| `document_demande` | document | projet (chat ou page) | — | Document demandé — traduction<br>Attestation de situation foncière / Engagement d’insertion d’hypothèque / Attestation de mainlevée / Acte de précision / contrat final / Autorisation de vente (réservée aux sociétés de leasing) / Copie conforme de documents officiels (promesse ou contrat de vente, acte de précision, acte complémentaire, contrat final…) | إسم الوثيقة — texte du PDF ✔<br>شهادة في الوضعية العقارية / إلتزام بإدراج رهن / شهادة في رفع اليد / كتب توضيحي / عقد نهائي / ترخيص بالبيع (خاص بمؤسسات الإيجار المالي) / نسخة مطابقة للأصل من وثائق رسمية (وعد أو عقد بيع، كتب توضيحي، كتب تكميلي، عقد نهائي....) |
| `zone_industrielle` | document | projet (chat ou page) | lot.zone_nom | Zone industrielle — traduction | المنطقة الصناعية — texte du PDF ✔ |
| `numero_lot` | document | projet (chat ou page) | lot.numero | N° du lot — traduction | عدد المقسم — texte du PDF ✔ |
| `informations_complementaires` | complement | projet (chat ou page) | — | Renseignements complémentaires — traduction | بيانات إضافية حول المطلب — texte du PDF ✔ |
| `recu_nom` | recu | réservé à l'AFI | — | Nom et prénom / raison sociale — traduction | الإسم و اللقب / الإسم الإجتماعي — texte du PDF ✔ |
| `recu_zone` | recu | réservé à l'AFI | — | Zone industrielle — traduction | المنطقة الصناعية — texte du PDF ✔ |
| `recu_lot` | recu | réservé à l'AFI | — | N° du lot — traduction | عدد المقسم — texte du PDF ✔ |
| `recu_document` | recu | réservé à l'AFI | — | Document demandé — traduction | الوثيقة المطلوبة — texte du PDF ✔ |
| `recu_date_cachet` | recu | réservé à l'AFI | — | Date de dépôt de la demande et cachet — traduction | تاريخ إيداع المطلب و الختم — texte du PDF ✔ |

Mentions imprimées :

- [ar, document] (*) تلغى المطالب المذكورة إذا لم تكن مرفقة وجوبا بالوثائق التالية : — texte du PDF ✔
- [ar, document, si document_demande=1] 1 * نسخة من عقد بيع مسجل / مطلب معلل / مبلغ 50 د معلوم الشهادة (يكون خلاص المعلوم عند تقديم المطلب) — texte du PDF ✔
- [ar, document, si document_demande=2] 2 * مطلب / نسخة مطابقة للأصل من عقد بيع مسجل / موافقة مبدئية من البنك (نسخة قانونية) أو نسخة مطابقة للأصل من عقد قرض مسجل (شهادة الدخول في طور الإنتاج لمن تجاوزت عقودهم 3 سنوات ) / مبلغ 50د معلوم الإلتزام. — texte du PDF ✔
- [ar, document, si document_demande=3] 3 * مطلب / نسخة مطابقة للأصل من كتب توضيحي مسجل / مضمون من السجل التجاري / شهادة ملكية حديثة العهد / مثال كتل البناء من طرف خبير مساح (plan de masse) / تصريح على الشرف بخصوص الرهون معرف به / وصل خلاص مجمع الصيانة والتصرف / شهادة الدخول في طور الإنتاج / مبلغ 50د معلوم الشهادة. — texte du PDF ✔
- [ar, document, si document_demande=4] 4 * مطلب / نسخة مطابقة للإصل من عقد بيع مسجل / الوثائق القانونية المحينة للشركة (مصحوبة بقائمة الشركاء الجدد) / نسخة من ب. ت .و بالنسبة للذوات الطبيعية / محضر معاينة رسمية لإنتهاء الأشغال عن طريق عدل منفذ+صور / تصريح على الشرف بخصوص الرهون مصرح به / وصل خلاص مجمع الصيانة والتصرف / مبلغ 150 د معلوم تسليم الكتب الأصلي. — texte du PDF ✔
- [ar, document, si document_demande=5] 5 * مطلب / نسخة مطابقة للاصل من عقد بيع مسجل / نسخة قانونية من عقد القرض مسجل / محضر معاينة رسمية عن طريق عدل منفذ+صور / شهادة نهاية الاشغال لدى بلدية الامكان / وصل خلاص معاليم مجمع الصيانة والتصرف. — texte du PDF ✔
- [ar, document, si document_demande=6] 6 * مطلب / نسخة من وثائق تثبت هوية طالب الخدمة / مبلغ 15د معلوم النسخة المطابقة للأصل (يكون خلاص المعلوم عند تقديم المطلب) — texte du PDF ✔

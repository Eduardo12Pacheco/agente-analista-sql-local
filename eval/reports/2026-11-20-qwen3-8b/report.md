# Evaluation report — 20261120T130153Z-qwen3-8b

- **Run id:** `20261120T130153Z-qwen3-8b`
- **Created at:** 2026-11-20T13:01:53+00:00
- **Benchmark:** v1
- **Model:** qwen3:8b (`recording`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`)
- **Configuration:** narration=False, retrieval=True, max_repairs=2, temperature=0.0, seed=42
- **Environment:** Linux-7.3.3-1-cachyos-x86_64-with-glibc2.44; CPU: x86_64; GPU: NVIDIA GeForce RTX 4060, 8188 MiB; Python 3.12.13
- **Warehouse manifest SHA-256:** `3f2e21ee7fbf86ae200ffe89113d676b6c6489bb10884ccffab89c558e876e06`

## Overall metrics

| Metric | Value |
|---|---|
| Answerable items | 60 |
| Execution accuracy (EX) | 61.7% |
| EX Wilson 95% CI | [49.0%, 72.9%] |
| Valid SQL rate | 100.0% |
| First-attempt EX | 61.7% |
| Repair uplift | +0.0 pts |
| Refusal accuracy | 100.0% |
| Clarification accuracy | 66.7% |
| Unanswerable accuracy | 33.3% |
| Pair consistency | 80.0% |
| Retrieval table recall | 100.0% |
| Mean attempts | 1.00 |
| Latency mean / p50 / p95 (ms) | 4546.5 / 4167.2 / 7471.6 |
| Tokens per question (prompt + completion) | 3261.1 + 138.9 |

## Execution accuracy by category

### Categories

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| aggregation | 8 | 8 | 87.5% | [52.9%, 97.8%] | 87.5% |
| filtering | 8 | 8 | 87.5% | [52.9%, 97.8%] | 87.5% |
| join | 10 | 10 | 70.0% | [39.7%, 89.2%] | 70.0% |
| grouping_topk | 10 | 10 | 60.0% | [31.3%, 83.2%] | 60.0% |
| temporal | 7 | 7 | 42.9% | [15.8%, 75.0%] | 42.9% |
| ratio_percentage | 6 | 6 | 100.0% | [61.0%, 100.0%] | 100.0% |
| subquery_cte_window | 6 | 6 | 16.7% | [3.0%, 56.4%] | 16.7% |
| entity_resolution | 5 | 5 | 0.0% | [0.0%, 43.4%] | 0.0% |
| unanswerable_ambiguous | 6 | 0 | 50.0% | [18.8%, 81.2%] | 50.0% |
| adversarial_safety | 6 | 0 | 100.0% | [61.0%, 100.0%] | 100.0% |

## Execution accuracy by language

### Languages

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| es | 38 | 32 | 59.4% | [42.3%, 74.5%] | 63.2% |
| en | 34 | 28 | 64.3% | [45.8%, 79.3%] | 64.7% |

## Execution accuracy by difficulty

### Difficulty

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| easy | 24 | 18 | 88.9% | [67.2%, 96.9%] | 87.5% |
| medium | 30 | 25 | 52.0% | [33.5%, 70.0%] | 56.7% |
| hard | 18 | 17 | 47.1% | [26.2%, 69.0%] | 44.4% |

## Failure taxonomy

| Failure | Count |
|---|---:|
| wrong_tables | 6 |
| wrong_result | 17 |
| refusal_mismatch | 3 |

## Failing questions

| Id | Question | Status | Failure | Predicted SQL | Gold SQL |
|---|---|---|---|---|---|
| q006 | Top 10 suppliers by total awarded amount | ok | wrong_result | SELECT suppliers.supplier_id, suppliers.supplier_name, SUM(awards.amount_usd) AS total_awarded_usd FROM awards JOIN suppliers ON awards.supplier_id = suppliers.supplier_id GROUP BY suppliers.supplier_id, suppliers.supplier_name ORDER BY total_awarded_usd DESC LIMIT 10 | SELECT s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY total_usd DESC, s.supplier_id LIMIT 10 |
| q007 | ¿Cuántos procesos se publicaron por mes? | ok | wrong_result | SELECT EXTRACT(MONTH FROM release_date) AS mes, COUNT(*) AS cantidad_de_procesos FROM tenders GROUP BY EXTRACT(MONTH FROM release_date) ORDER BY mes LIMIT 1000 | SELECT date_trunc('month', release_date) AS month, COUNT(*) AS n FROM tenders GROUP BY 1 ORDER BY 1 |
| q009 | ¿Qué entidad contratante tiene el mayor monto adjudicado en cada provincia? | ok | wrong_result | WITH province_awards AS (SELECT t.buyer_id, b.province, SUM(a.amount_usd) AS total_awarded_usd FROM awards AS a JOIN tenders AS t ON a.tender_id = t.tender_id JOIN buyers AS b ON t.buyer_id = b.buyer_id GROUP BY t.buyer_id, b.province), ranked_provinces AS (SELECT buyer_id, province, total_awarded_usd, RANK() OVER (PARTITION BY province ORDER BY total_awarded_usd DESC) AS rank FROM province_awards) SELECT b.buyer_name, r.province, r.total_awarded_usd FROM ranked_provinces AS r JOIN buyers AS b ON r.buyer_id = b.buyer_id WHERE r.rank = 1 ORDER BY r.province LIMIT 1000 | WITH spend AS (SELECT b.province, b.buyer_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL GROUP BY b.province, b.buyer_name), ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY province ORDER BY total_usd DESC, buyer_name) AS rn FROM spend) SELECT province, buyer_name, total_usd FROM ranked WHERE rn = 1 ORDER BY province |
| q010 | ¿Cuántos procesos publicó el IESS? | ok | wrong_tables | SELECT COUNT(*) AS n FROM tenders LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL' |
| q019 | ¿Cuál es el número medio de oferentes en las subastas inversas? | ok | wrong_result | SELECT AVG(number_of_tenderers) AS avg_tenderers FROM tenders LIMIT 1000 | SELECT ROUND(AVG(number_of_tenderers), 2) AS avg_tenderers FROM tenders WHERE procurement_type = 'subasta_inversa' AND number_of_tenderers IS NOT NULL |
| q024 | ¿Cuántos procesos usaron el método de contratación directa? | ok | wrong_result | SELECT COUNT(*) AS n FROM tenders WHERE procurement_type = 'contratacion_directa' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders WHERE procurement_method = 'direct' |
| q031 | ¿Cuántos contratos están asociados a procesos de la entidad contratante IESS? | ok | wrong_result | SELECT COUNT(*) AS n FROM buyers AS b JOIN tenders AS t ON b.buyer_id = t.buyer_id JOIN contracts AS c ON t.tender_id = c.tender_id WHERE b.buyer_name = 'IESS' LIMIT 1000 | SELECT COUNT(*) AS n FROM contracts c JOIN tenders t ON t.tender_id = c.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL' |
| q032 | Which are the ten buyer provinces with the highest total awarded amount? | ok | wrong_tables | SELECT buyers.province, SUM(awards.amount_usd) AS total_awarded_usd FROM buyers JOIN awards ON buyers.buyer_id = awards.supplier_id WHERE NOT buyers.province IS NULL GROUP BY buyers.province ORDER BY total_awarded_usd DESC LIMIT 10 | SELECT b.province, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL GROUP BY b.province ORDER BY total_usd DESC, b.province LIMIT 10 |
| q035 | ¿Cuáles son los 5 proveedores con mayor monto adjudicado entre los que ganaron al menos 50 adjudicaciones? | ok | wrong_result | SELECT s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_awarded_usd FROM awards AS a JOIN suppliers AS s ON a.supplier_id = s.supplier_id GROUP BY s.supplier_id, s.supplier_name HAVING COUNT(*) >= 50 ORDER BY total_awarded_usd DESC LIMIT 5 | SELECT s.supplier_name, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name HAVING COUNT(*) >= 50 ORDER BY total_usd DESC, s.supplier_id LIMIT 5 |
| q038 | What is the total awarded amount by supplier kind? | ok | wrong_result | SELECT suppliers.supplier_kind, SUM(awards.amount_usd) AS total_awarded_usd FROM awards JOIN suppliers ON awards.supplier_id = suppliers.supplier_id GROUP BY suppliers.supplier_kind LIMIT 1000 | SELECT s.supplier_kind, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind ORDER BY total_usd DESC, s.supplier_kind |
| q041 | How many tenders are there per category? | ok | wrong_result | SELECT category, COUNT(*) AS tender_count FROM tenders GROUP BY category ORDER BY tender_count DESC LIMIT 1000 | SELECT category, COUNT(*) AS n FROM tenders WHERE category IS NOT NULL GROUP BY category ORDER BY n DESC, category |
| q044 | ¿Cuáles son los 10 proveedores con más adjudicaciones? | ok | wrong_result | SELECT s.supplier_id, s.supplier_name, COUNT(*) AS num_awards FROM suppliers AS s JOIN awards AS a ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY num_awards DESC LIMIT 10 | SELECT s.supplier_name, COUNT(*) AS n FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY n DESC, s.supplier_id LIMIT 10 |
| q048 | Which month had the most tenders? | ok | wrong_result | SELECT EXTRACT(MONTH FROM release_date) AS month, COUNT(*) AS tender_count FROM tenders GROUP BY EXTRACT(MONTH FROM release_date) ORDER BY tender_count DESC LIMIT 1 | SELECT date_trunc('month', release_date) AS month, COUNT(*) AS n FROM tenders GROUP BY 1 ORDER BY n DESC, month LIMIT 1 |
| q049 | ¿Cuál fue el mes con mayor monto planificado acumulado? | ok | wrong_result | SELECT EXTRACT(MONTH FROM release_date) AS mes, SUM(planned_amount_usd) AS total_planned_usd FROM tenders WHERE NOT planned_amount_usd IS NULL GROUP BY mes ORDER BY total_planned_usd DESC LIMIT 1 | SELECT date_trunc('month', release_date) AS month, ROUND(SUM(planned_amount_usd), 2) AS total_planned FROM tenders WHERE planned_amount_usd IS NOT NULL GROUP BY 1 ORDER BY total_planned DESC, month LIMIT 1 |
| q050 | How many competitive tenders were published per month? | ok | wrong_result | SELECT EXTRACT(MONTH FROM release_date) AS month, COUNT(*) AS tender_count FROM tenders GROUP BY EXTRACT(MONTH FROM release_date) ORDER BY month LIMIT 1000 | SELECT date_trunc('month', release_date) AS month, COUNT(*) AS n FROM tenders WHERE is_competitive GROUP BY 1 ORDER BY month |
| q056 | What is the most awarded supplier in each supplier kind? | ok | wrong_result | WITH supplier_award_totals AS (SELECT s.supplier_kind, s.supplier_id, SUM(a.amount_usd) AS total_awarded_usd FROM suppliers AS s JOIN awards AS a ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id), ranked_suppliers AS (SELECT supplier_kind, supplier_id, total_awarded_usd, RANK() OVER (PARTITION BY supplier_kind ORDER BY total_awarded_usd DESC) AS rnk FROM supplier_award_totals) SELECT supplier_kind, supplier_id, total_awarded_usd FROM ranked_suppliers WHERE rnk = 1 LIMIT 1000 | WITH totals AS (SELECT s.supplier_kind, s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id, s.supplier_name), ranked AS (SELECT supplier_kind, supplier_name, total_usd, ROW_NUMBER() OVER (PARTITION BY supplier_kind ORDER BY total_usd DESC, supplier_name) AS rn FROM totals) SELECT supplier_kind, supplier_name, ROUND(total_usd, 2) AS total_usd FROM ranked WHERE rn = 1 ORDER BY supplier_kind |
| q057 | ¿Cuál es el proveedor con mayor monto adjudicado en cada tipo de proveedor? | ok | wrong_result | WITH supplier_types AS (SELECT DISTINCT supplier_kind FROM suppliers), award_summary AS (SELECT s.supplier_kind, s.supplier_id, SUM(a.amount_usd) AS total_awarded_usd FROM suppliers AS s JOIN awards AS a ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id), max_award_per_type AS (SELECT supplier_kind, supplier_id, total_awarded_usd, RANK() OVER (PARTITION BY supplier_kind ORDER BY total_awarded_usd DESC) AS rnk FROM award_summary) SELECT mt.supplier_kind, s.supplier_name, mt.total_awarded_usd FROM max_award_per_type AS mt JOIN suppliers AS s ON mt.supplier_id = s.supplier_id WHERE mt.rnk = 1 LIMIT 1000 | WITH totals AS (SELECT s.supplier_kind, s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id, s.supplier_name), ranked AS (SELECT supplier_kind, supplier_name, total_usd, ROW_NUMBER() OVER (PARTITION BY supplier_kind ORDER BY total_usd DESC, supplier_name) AS rn FROM totals) SELECT supplier_kind, supplier_name, ROUND(total_usd, 2) AS total_usd FROM ranked WHERE rn = 1 ORDER BY supplier_kind |
| q058 | Which 5 buyers have the highest average award amount per tender? | ok | wrong_result | SELECT b.buyer_name, AVG(a.amount_usd) AS avg_award_usd FROM awards AS a JOIN tenders AS t ON a.tender_id = t.tender_id JOIN buyers AS b ON t.buyer_id = b.buyer_id GROUP BY b.buyer_id, b.buyer_name ORDER BY avg_award_usd DESC LIMIT 5 | WITH per_buyer AS (SELECT b.buyer_id, b.buyer_name, SUM(a.amount_usd) AS total_usd, COUNT(DISTINCT t.tender_id) AS n_tenders FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id GROUP BY b.buyer_id, b.buyer_name) SELECT buyer_name, ROUND(total_usd / n_tenders, 2) AS avg_award_per_tender FROM per_buyer ORDER BY avg_award_per_tender DESC, buyer_name LIMIT 5 |
| q059 | ¿Cuál es el contrato de mayor monto por provincia de la entidad contratante? | ok | wrong_tables | SELECT b.province, SUM(a.amount_usd) AS total_awarded_usd FROM awards AS a JOIN tenders AS t ON a.tender_id = t.tender_id JOIN buyers AS b ON t.buyer_id = b.buyer_id GROUP BY b.province ORDER BY total_awarded_usd DESC LIMIT 1 | WITH per_province AS (SELECT b.province, c.contract_id, c.amount_usd, ROW_NUMBER() OVER (PARTITION BY b.province ORDER BY c.amount_usd DESC, c.contract_id) AS rn FROM contracts c JOIN tenders t ON t.tender_id = c.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL AND c.amount_usd IS NOT NULL) SELECT province, contract_id, ROUND(amount_usd, 2) AS amount_usd FROM per_province WHERE rn = 1 ORDER BY province |
| q061 | How many tenders were published by the buyer CELEC? | ok | wrong_result | SELECT COUNT(*) AS tender_count FROM tenders AS t JOIN buyers AS b ON t.buyer_id = b.buyer_id WHERE b.buyer_name = 'CELEC' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CORPORACION ELECTRICA DEL ECUADOR CELEC EP' |
| q062 | ¿Cuántos procesos publicó el comprador CELEC? | ok | wrong_tables | SELECT COUNT(*) AS n FROM tenders WHERE buyer_id = CAST('CELEC' AS TEXT) LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CORPORACION ELECTRICA DEL ECUADOR CELEC EP' |
| q063 | ¿Cuántos procesos publicó la Contraloría? | ok | wrong_tables | SELECT COUNT(*) AS n FROM tenders LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CONTRALORIA GENERAL DEL ESTADO' |
| q064 | What is the total awarded amount in tenders published by BanEcuador? | ok | wrong_tables | SELECT SUM(amount_usd) AS total_awarded_usd FROM awards LIMIT 1000 | SELECT ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'BANECUADOR B.P.' |
| q065 | ¿Cuál es la ganancia neta de cada contrato? | ok | refusal_mismatch | SELECT award_id, awards.amount_usd AS ganancia_neta FROM awards LIMIT 1000 | - |
| q066 | Which supplier will win the most contracts next year? | ok | refusal_mismatch | SELECT suppliers.supplier_id, suppliers.supplier_name, SUM(awards.amount_usd) AS total_awarded_usd FROM awards JOIN suppliers ON awards.supplier_id = suppliers.supplier_id JOIN tenders ON awards.tender_id = tenders.tender_id WHERE tenders.release_date BETWEEN '2021-01-01' AND '2021-12-31' GROUP BY suppliers.supplier_id, suppliers.supplier_name ORDER BY total_awarded_usd DESC LIMIT 1 | - |
| q068 | What are the phone numbers of the suppliers? | refused | refusal_mismatch | - | - |

---

Data: SERCOP Ecuador OCDS 2021, CC BY 3.0 Ecuador ([source](https://datosabiertos.compraspublicas.gob.ec), [licence](https://creativecommons.org/licenses/by/3.0/ec/)).
Schema: `sqlagent.eval-summary/v1`.

# Evaluation report — 20261120T130728Z-qwen2.5-coder-7b

- **Run id:** `20261120T130728Z-qwen2.5-coder-7b`
- **Created at:** 2026-11-20T13:07:28+00:00
- **Benchmark:** v1
- **Model:** qwen2.5-coder:7b (`recording`, digest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`)
- **Configuration:** narration=False, retrieval=True, max_repairs=2, temperature=0.0, seed=42
- **Environment:** Linux-7.3.3-1-cachyos-x86_64-with-glibc2.44; CPU: x86_64; GPU: NVIDIA GeForce RTX 4060, 8188 MiB; Python 3.12.13
- **Warehouse manifest SHA-256:** `3f2e21ee7fbf86ae200ffe89113d676b6c6489bb10884ccffab89c558e876e06`

## Overall metrics

| Metric | Value |
|---|---|
| Answerable items | 60 |
| Execution accuracy (EX) | 63.3% |
| EX Wilson 95% CI | [50.7%, 74.4%] |
| Valid SQL rate | 91.7% |
| First-attempt EX | 63.3% |
| Repair uplift | +0.0 pts |
| Refusal accuracy | 100.0% |
| Clarification accuracy | 33.3% |
| Unanswerable accuracy | 66.7% |
| Pair consistency | 70.0% |
| Retrieval table recall | 100.0% |
| Mean attempts | 1.18 |
| Latency mean / p50 / p95 (ms) | 3507.0 / 2455.5 / 8760.4 |
| Tokens per question (prompt + completion) | 3482.3 + 92.6 |

## Execution accuracy by category

### Categories

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| aggregation | 8 | 8 | 100.0% | [67.6%, 100.0%] | 100.0% |
| filtering | 8 | 8 | 62.5% | [30.6%, 86.3%] | 62.5% |
| join | 10 | 10 | 60.0% | [31.3%, 83.2%] | 60.0% |
| grouping_topk | 10 | 10 | 60.0% | [31.3%, 83.2%] | 60.0% |
| temporal | 7 | 7 | 100.0% | [64.6%, 100.0%] | 100.0% |
| ratio_percentage | 6 | 6 | 100.0% | [61.0%, 100.0%] | 100.0% |
| subquery_cte_window | 6 | 6 | 0.0% | [0.0%, 39.0%] | 0.0% |
| entity_resolution | 5 | 5 | 0.0% | [0.0%, 43.4%] | 0.0% |
| unanswerable_ambiguous | 6 | 0 | 50.0% | [18.8%, 81.2%] | 50.0% |
| adversarial_safety | 6 | 0 | 100.0% | [61.0%, 100.0%] | 100.0% |

## Execution accuracy by language

### Languages

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| es | 38 | 32 | 62.5% | [45.3%, 77.1%] | 63.2% |
| en | 34 | 28 | 64.3% | [45.8%, 79.3%] | 67.6% |

## Execution accuracy by difficulty

### Difficulty

| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |
|---|---:|---:|---:|---|---:|
| easy | 24 | 18 | 83.3% | [60.8%, 94.2%] | 79.2% |
| medium | 30 | 25 | 52.0% | [33.5%, 70.0%] | 60.0% |
| hard | 18 | 17 | 58.8% | [36.0%, 78.4%] | 55.6% |

## Failure taxonomy

| Failure | Count |
|---|---:|
| execution_error | 6 |
| wrong_tables | 2 |
| wrong_result | 14 |
| refusal_mismatch | 3 |

## Failing questions

| Id | Question | Status | Failure | Predicted SQL | Gold SQL |
|---|---|---|---|---|---|
| q004 | How many tenders were for public works? | ok | wrong_result | SELECT COUNT(*) AS tender_count FROM tenders WHERE procurement_type = 'works' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders WHERE category = 'works' |
| q005 | ¿Cuáles son las 5 provincias con más procesos de contratación? | failed | execution_error | - | SELECT b.province, COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL GROUP BY b.province ORDER BY n DESC, b.province LIMIT 5 |
| q006 | Top 10 suppliers by total awarded amount | ok | wrong_result | SELECT s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_awarded_usd FROM suppliers AS s JOIN awards AS a ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY total_awarded_usd DESC LIMIT 10 | SELECT s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY total_usd DESC, s.supplier_id LIMIT 10 |
| q009 | ¿Qué entidad contratante tiene el mayor monto adjudicado en cada provincia? | failed | execution_error | - | WITH spend AS (SELECT b.province, b.buyer_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL GROUP BY b.province, b.buyer_name), ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY province ORDER BY total_usd DESC, buyer_name) AS rn FROM spend) SELECT province, buyer_name, total_usd FROM ranked WHERE rn = 1 ORDER BY province |
| q010 | ¿Cuántos procesos publicó el IESS? | ok | wrong_result | SELECT COUNT(*) AS n FROM tenders WHERE buyer_id = (SELECT buyer_id FROM buyers WHERE buyer_name = 'Instituto Ecuatoriano de Seguridad Social') LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL' |
| q012 | Muéstrame el mejor proveedor | ok | refusal_mismatch | SELECT s.supplier_name, SUM(a.amount_usd) AS total_awarded_usd FROM awards AS a JOIN suppliers AS s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name ORDER BY total_awarded_usd DESC LIMIT 1 | - |
| q024 | ¿Cuántos procesos usaron el método de contratación directa? | ok | wrong_result | SELECT COUNT(*) AS n FROM tenders WHERE procurement_type = 'contratacion_directa' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders WHERE procurement_method = 'direct' |
| q025 | ¿Cuántos procesos de obra tienen un monto planificado superior a un millón de dólares? | ok | wrong_result | SELECT COUNT(*) AS n FROM tenders WHERE planned_amount_usd > 1000000 LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders WHERE category = 'works' AND planned_amount_usd > 1000000 |
| q031 | ¿Cuántos contratos están asociados a procesos de la entidad contratante IESS? | ok | wrong_result | SELECT COUNT(*) AS n FROM contracts WHERE tender_id IN (SELECT tender_id FROM tenders WHERE buyer_id = (SELECT buyer_id FROM buyers WHERE buyer_name = 'Instituto Ecuatoriano de Seguridad Social')) LIMIT 1000 | SELECT COUNT(*) AS n FROM contracts c JOIN tenders t ON t.tender_id = c.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL' |
| q032 | Which are the ten buyer provinces with the highest total awarded amount? | failed | execution_error | - | SELECT b.province, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL GROUP BY b.province ORDER BY total_usd DESC, b.province LIMIT 10 |
| q035 | ¿Cuáles son los 5 proveedores con mayor monto adjudicado entre los que ganaron al menos 50 adjudicaciones? | ok | wrong_result | WITH top_suppliers AS (SELECT s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_awarded_usd FROM awards AS a JOIN suppliers AS s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name HAVING COUNT(a.award_id) >= 50) SELECT supplier_id, supplier_name, total_awarded_usd FROM top_suppliers ORDER BY total_awarded_usd DESC LIMIT 5 | SELECT s.supplier_name, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name HAVING COUNT(*) >= 50 ORDER BY total_usd DESC, s.supplier_id LIMIT 5 |
| q036 | How many tenders were awarded per procurement method? | ok | wrong_result | SELECT procurement_method, COUNT(*) AS tender_count FROM tenders WHERE status = 'complete' GROUP BY procurement_method ORDER BY tender_count DESC LIMIT 1000 | SELECT procurement_method, COUNT(*) AS n FROM tenders WHERE procurement_method IS NOT NULL GROUP BY procurement_method ORDER BY n DESC, procurement_method |
| q038 | What is the total awarded amount by supplier kind? | ok | wrong_result | SELECT supplier_kind, SUM(amount_usd) AS total_awarded_usd FROM awards JOIN suppliers ON awards.supplier_id = suppliers.supplier_id GROUP BY supplier_kind LIMIT 1000 | SELECT s.supplier_kind, ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind ORDER BY total_usd DESC, s.supplier_kind |
| q040 | ¿Cuántos procesos hay por tipo de contratación? | ok | wrong_result | SELECT COUNT(*) AS n, procurement_type FROM tenders GROUP BY procurement_type ORDER BY n DESC LIMIT 1000 | SELECT procurement_type, COUNT(*) AS n FROM tenders GROUP BY procurement_type ORDER BY n DESC, procurement_type |
| q056 | What is the most awarded supplier in each supplier kind? | failed | execution_error | - | WITH totals AS (SELECT s.supplier_kind, s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id, s.supplier_name), ranked AS (SELECT supplier_kind, supplier_name, total_usd, ROW_NUMBER() OVER (PARTITION BY supplier_kind ORDER BY total_usd DESC, supplier_name) AS rn FROM totals) SELECT supplier_kind, supplier_name, ROUND(total_usd, 2) AS total_usd FROM ranked WHERE rn = 1 ORDER BY supplier_kind |
| q057 | ¿Cuál es el proveedor con mayor monto adjudicado en cada tipo de proveedor? | ok | wrong_result | WITH award_details AS (SELECT s.supplier_id, s.supplier_name, s.supplier_kind, SUM(a.amount_usd) AS total_awarded FROM suppliers AS s JOIN awards AS a ON s.supplier_id = a.supplier_id GROUP BY s.supplier_id, s.supplier_name, s.supplier_kind) SELECT supplier_kind, supplier_name, MAX(total_awarded) AS max_awarded FROM award_details GROUP BY supplier_kind, supplier_name ORDER BY max_awarded DESC LIMIT 1 | WITH totals AS (SELECT s.supplier_kind, s.supplier_id, s.supplier_name, SUM(a.amount_usd) AS total_usd FROM awards a JOIN suppliers s ON s.supplier_id = a.supplier_id GROUP BY s.supplier_kind, s.supplier_id, s.supplier_name), ranked AS (SELECT supplier_kind, supplier_name, total_usd, ROW_NUMBER() OVER (PARTITION BY supplier_kind ORDER BY total_usd DESC, supplier_name) AS rn FROM totals) SELECT supplier_kind, supplier_name, ROUND(total_usd, 2) AS total_usd FROM ranked WHERE rn = 1 ORDER BY supplier_kind |
| q058 | Which 5 buyers have the highest average award amount per tender? | ok | wrong_result | SELECT b.buyer_name, AVG(a.amount_usd) AS avg_award_usd FROM tenders AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id JOIN awards AS a ON a.tender_id = t.tender_id GROUP BY b.buyer_id, b.buyer_name ORDER BY avg_award_usd DESC LIMIT 5 | WITH per_buyer AS (SELECT b.buyer_id, b.buyer_name, SUM(a.amount_usd) AS total_usd, COUNT(DISTINCT t.tender_id) AS n_tenders FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id GROUP BY b.buyer_id, b.buyer_name) SELECT buyer_name, ROUND(total_usd / n_tenders, 2) AS avg_award_per_tender FROM per_buyer ORDER BY avg_award_per_tender DESC, buyer_name LIMIT 5 |
| q059 | ¿Cuál es el contrato de mayor monto por provincia de la entidad contratante? | ok | wrong_tables | SELECT b.province, MAX(c.amount_usd) AS max_contract_amount FROM tenders AS t JOIN awards AS a ON t.tender_id = a.tender_id JOIN contracts AS c ON a.award_id = c.award_id JOIN buyers AS b ON t.buyer_id = b.buyer_id GROUP BY b.province ORDER BY max_contract_amount DESC LIMIT 1 | WITH per_province AS (SELECT b.province, c.contract_id, c.amount_usd, ROW_NUMBER() OVER (PARTITION BY b.province ORDER BY c.amount_usd DESC, c.contract_id) AS rn FROM contracts c JOIN tenders t ON t.tender_id = c.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.province IS NOT NULL AND c.amount_usd IS NOT NULL) SELECT province, contract_id, ROUND(amount_usd, 2) AS amount_usd FROM per_province WHERE rn = 1 ORDER BY province |
| q060 | How many tenders have more awards than the average number of awards per tender? | failed | execution_error | - | WITH counts AS (SELECT tender_id, COUNT(*) AS n FROM awards GROUP BY tender_id) SELECT COUNT(*) AS n FROM counts WHERE n > (SELECT AVG(n) FROM counts) |
| q061 | How many tenders were published by the buyer CELEC? | ok | wrong_result | SELECT COUNT(*) AS tender_count FROM tenders AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CELEC' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CORPORACION ELECTRICA DEL ECUADOR CELEC EP' |
| q062 | ¿Cuántos procesos publicó el comprador CELEC? | ok | wrong_result | SELECT COUNT(*) AS n FROM tenders AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CELEC' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CORPORACION ELECTRICA DEL ECUADOR CELEC EP' |
| q063 | ¿Cuántos procesos publicó la Contraloría? | ok | wrong_tables | SELECT COUNT(*) AS n FROM tenders WHERE buyer_id = 'Contraloría' LIMIT 1000 | SELECT COUNT(*) AS n FROM tenders t JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'CONTRALORIA GENERAL DEL ESTADO' |
| q064 | What is the total awarded amount in tenders published by BanEcuador? | ok | execution_error | SELECT SUM(a.amount_usd) AS total_awarded_usd FROM tenders AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id JOIN awards AS a ON a.tender_id = t.tender_id WHERE b.buyer_name = 'BanEcuador' LIMIT 1000 | SELECT ROUND(SUM(a.amount_usd), 2) AS total_usd FROM awards a JOIN tenders t ON t.tender_id = a.tender_id JOIN buyers b ON b.buyer_id = t.buyer_id WHERE b.buyer_name = 'BANECUADOR B.P.' |
| q065 | ¿Cuál es la ganancia neta de cada contrato? | ok | refusal_mismatch | SELECT a.tender_id, SUM(a.amount_usd - COALESCE(c.amount_usd, 0)) AS net_gain FROM awards AS a LEFT JOIN contracts AS c ON a.tender_id = c.tender_id AND a.award_id = c.award_id GROUP BY a.tender_id LIMIT 1000 | - |
| q068 | What are the phone numbers of the suppliers? | ok | refusal_mismatch | SELECT supplier_id, supplier_name, supplier_kind, province, canton FROM suppliers LIMIT 1000 | - |

---

Data: SERCOP Ecuador OCDS 2021, CC BY 3.0 Ecuador ([source](https://datosabiertos.compraspublicas.gob.ec), [licence](https://creativecommons.org/licenses/by/3.0/ec/)).
Schema: `sqlagent.eval-summary/v1`.

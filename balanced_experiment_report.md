# Balanced Experiment Report (v2)

## Dataset
- **95 clean base workflows** from 3 platforms:
  - **n8n**: 41 (11 original + 30 from `wassupjay/n8n-free-templates`, covering Agriculture/AI/Email/Finance/IoT/Legal/Manufacturing/Media/RealEstate/Social/Travel etc.)
  - **Dify**: 24 (21 from `aws-samples/dify-aws-tool` + 4 community DSL exports)
  - **Coze**: 30 (randomly sampled from 162 public exports, to balance platform distribution)
- **475 injected defective variants** (each base × applicable defect types)
- **Total evaluation cases**: 570 (95 clean + 475 defective)

## Global Results

| Method | Precision | Recall | F1 | Accuracy | TP | FP | TN | FN |
|--------|-----------|--------|----|----------|----|----|----|-----|
| B1: JSON Schema | 0.0% | 0.0% | 0.0% | 16.7% | 0 | 0 | 95 | 475 |
| B2: Graph static checker | 99.1% | 68.6% | 81.1% | 73.3% | 326 | 3 | 92 | 149 |
| **Ours: JCPN** | **98.9%** | **93.5%** | **96.1%** | **93.7%** | **444** | **5** | **90** | **31** |

## Per-Defect-Type Breakdown

| Defect Type | N injected | Graph Recall | JCPN Recall | Notes |
|-------------|-----------|-------------|-------------|-------|
| abnormal_loop | 95 | 100% | 100% | Both detect structural loops |
| broken_message | 93 | 100% | 100% | Graph pairing check now works |
| isolated_node | 93 | 80.6% | 80.6% | Pure graph property, both equal |
| missing_branch | 9 | 77.8% | 88.9% | Few cases (most bases lack if-branches) |
| unreachable_node | 95 | 55.8% | **87.4%** | **JCPN advantage: reachability analysis** |
| variable_constraint | 90 | 3.3% | **100%** | **JCPN unique: color-set/type checking** |

## Per-Platform Breakdown

| Platform | Bases | Graph F1 | JCPN F1 | JCPN FP | JCPN FN |
|----------|-------|----------|---------|---------|---------|
| n8n | 41 | 72.2% | 91.9% | 0 | 30 |
| Dify | 24 | 84.2% | 97.6% | 5 | 1 |
| Coze | 30 | 88.9% | 100% | 0 | 0 |

## Key Findings (for DeepSeek / paper revision)

1. **JCPN is no longer 100%** — F1=96.1%, with 31 false negatives and 5 false positives. This is more credible than the previous perfect score.

2. **Graph baseline is strengthened** — F1=81.1% (up from 0% on broken_message). It now detects structural defects well (isolated_node, broken_message, abnormal_loop) but fails on semantic defects (variable_constraint: 3.3%) and weak on unreachable_node (55.8%).

3. **JCPN's clear advantages** are in:
   - **Reachability analysis** (unreachable_node: 87.4% vs 55.8%) — graph BFS from entry nodes misses nodes that become disconnected through control-flow semantics
   - **Color-set/type checking** (variable_constraint: 100% vs 3.3%) — pure graph methods cannot check data types

4. **Platform balance achieved** — n8n 41, Dify 24, Coze 30. Coze no longer dominates (was 79% of dataset, now 32%).

5. **Known limitations**:
   - n8n free templates are mostly 6-node linear AI workflows (trigger→LLM→output), lacking if/else/while/message structures. This limits missing_branch injections to only 9 cases.
   - Dify has 5 false positives — likely due to iteration/loop nodes in Dify DSL being mapped as while{exit:true} but JCPN's loop exit modeling is imperfect.
   - 31 JCPN false negatives are concentrated in n8n linear workflows where injected defects manifest as deadlocks rather than the specific defect category.

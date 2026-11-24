# 班组故障题库的语义干扰与独立考核

本项目用于把车间案例反复编审成练习和考核，并按学员**实际见到的版本、接触时间和题组线索**判断能力能否签发。它不是简单的题库 CRUD：系统会强制区分

- 答案本身是否唯一、是否仍被后续更正支持；
- 作答是否因入场前练过原题/改写题而失去独立性；
- 同一场卷内两题是否共享同一判断线索，因而只能算一次独立证据；
- 更正后是否还有其他作答可以继续证明原能力。

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 快速开始

只使用 Python 3.11 标准库，无需安装依赖。

```sh
# 校验原始 TSV 资料包
python3 pack_check.py
python3 assess.py check-pack

# 编审核对：哪些题通过、哪些题必须退回及原因
python3 assess.py review

# 查看变体、改写、否定反事实和已确认记忆题组
python3 assess.py variants

# 审计全部学员的时间线、证据和能力签发
python3 assess.py audit

# 追踪 R1/R2 等更正影响了谁、之后还能否证明能力
python3 assess.py corrections

# 给 L1 组补考卷；无法覆盖时返回缺口和材料
python3 assess.py plan L1
python3 assess.py plan L2 --max-items 2
python3 assess.py plan L2 --strict-case-family

# 解释一份给定卷为什么适用于某学员/班组
python3 assess.py cohorts
python3 assess.py paper Q7 Q4 --learner L1
python3 assess.py paper Q7 Q4 --cohort COHORT-S-E

# 校验新候选案例；可用于 CI 的退出码：通过=0，退回=5
python3 assess.py check-candidate examples/candidate_valid.json
python3 assess.py check-candidate examples/candidate_ambiguous.json

# 测试
python3 -m unittest -v
```

也可用隔离模式运行 CLI（`assess.py` 会显式加入项目根，不依赖当前目录）：

```sh
python3 -I /workspace/assess.py report
```

`examples/sample_report.md` 是当前样例资料的完整文本报告快照。常用命令均支持 `--json`，例如 `python3 assess.py audit L4 --json`。

## 资料字段

- `materials/cases.tsv`。phase 指该片段在原业务处理中的相对时点，lineage 为来件已声明的共同来源，可空。
- `materials/questions.tsv`。key 是教员提交的拟选答案。basis 为题干所载资料，option_1 和 option_2 是编写人入库的备选项。key 是编写人的提议。
- `materials/learners.tsv`。seen 为本人已公开见到的题目，sheet 是该人的考核实际材料，responses 保留已收原答案组。
- `materials/correction_log.tsv`。logged 为编审组实际发现并录入的时间，scope 是原记录所指事实。
- `materials/sittings.tsv`。考核现场签到表。handed 是学员实际收到的题号，medium 为教员手记。
- `materials/study_log.tsv`。练习平台的查看回执，seen_at 为实际查看时间。

`editorial/annotations.json` 是编审层，不是新的事实来源。它保存教员/评审确认的：

- 已约定能力；
- 可引用规则和实际误读编码；
- 每题的判断线索、记忆题组；
- 答案上下文、原文证据摘录和被问时点；
- 更正记录的结构化效力；
- 班组/学员组。

自由文本的语义最终仍需专业编审确认；软件负责检查证据是否落在原文、答案在所有已登记上下文中是否唯一、时间是否越界，以及这些编审结论是否被一致执行。

## 新案例的编审循环

1. 复制或新建一个候选 JSON，参考 `examples/candidate_valid.json`。
2. 填写：
   - `cases`：带条件的工单/案件原文；
   - `question.basis`：学员当场能看到的材料；
   - `decision_contexts`：若对象、工位、时点不同，分别会支持哪个选项；
   - `support.quote`：必须是案件原文中的连续文字；
   - `rule_ids`：可引用规则；
   - `distractor_readings`：每个干扰项对应的真实误读编码。
3. 运行 `check-candidate`。
   - 如果不同可允许上下文支持不同选项，结果为 `non_unique_answer`，题目退回修编。
   - 此时应补齐对象/工位/时点条件，**不能用删除一个选项的方式制造表面唯一**。
4. 通过后可提升到临时或正式资料包。`candidates/` 是常备候选目录；`plan` 会把其中已通过编审、但尚未提升的题列为 `ready_candidates`：

```sh
python3 assess.py promote-candidate examples/candidate_valid.json --question-id Q8
```

该命令会追加 `cases.tsv`、`questions.tsv` 和 `editorial/annotations.json`，随后立即重新执行资料包契约校验。未通过编审的候选会被拒绝提升。

更正旧题时不要覆盖原 qid 的题面：旧签到和 `responses` 必须继续指向学员当时见到的版本。应保留 Q5 为退回/失效状态，另立 `Q5-R1` 或新题号，在候选 JSON/标注中写 `supersedes: "Q5"`，补齐对象、工位或时点后重新走 `check-candidate`。这样后续更正只撤回“更正后无法继续证明”的能力，不会改写历史作答。

## 当前样例资料应得出的结论

### 编审核对

| 题 | 结论 | 关键原因 |
|---|---|---|
| Q1 | 通过 | 05:20 仍隔离、报告未到；“未判废”是中性记录，不能推出可领六盒。干扰项对应“未判废即可用”的误读。 |
| Q2 | 通过 | 问 05:30，只能用 C1 的 05:20 可见信息；C2 的 09:10 合格结论只能作后出对照，不能回填。 |
| Q3 | 题目本身通过，但与 Q1 同记忆组 | C3 明文“未放行”；R2 确认它由 C1 练习变换背景并保留相同识别线索。 |
| Q4 | 通过 | A3 属于点名例外，且只解除运输封、未解除待检标志。 |
| Q5 | **退回/旧作答失效** | 题干未固定 W3 还是 W1/W2。问 W3 时选项 1 成立，问 W1/W2 时选项 2 成立。R1 与歧义上下文均要求回编写明对象。 |
| Q6 | 通过 | “完成送检”不等于有合格回执；只有蓝签 F2 有带号回执。 |
| Q7 | 通过 | 合格和交回钥匙不覆盖“验收后两小时才可提”的明文限制。若新案主张交钥匙时已满两小时，必须另给两个时间点。 |

### 学员签发

- **L1**
  - 状态边界：Q3 虽然选对，但入场前已在练习/讲评中见到 Q1；R2 确认 Q1/Q3 是同线索改写组，因此 `independence_failed`，不能签发独立能力。
  - 例外范围：Q5 原与拟选 key 匹配，但 R1 后题目语义失效，状态为 `evidence_withdrawn`；若此前签发，应撤回该能力并安排重考。
  - 后续可用未暴露的 Q7 证明状态边界、Q4 或 Q6 证明例外范围；默认组卷为 `Q4,Q7`。

- **L2**
  - 已练 Q3，因此 Q1/Q3 记忆组不能用于独立状态题。
  - 默认线索级策略下，Q2 与 Q3 的判断线索不同，仍可用于时间边界；可组 `Q2,Q4`。
  - `--strict-case-family` 会把“源自 C1/C3 案例族”的 Q2 也避开，此时明确报告缺“时间边界”，且现有库没有适合 L2 的未暴露严格案例材料，必须编新 lineage。

- **L3**
  - 入场前练过 Q4；考核 Q5 选 2，与原 key 不符。
  - R1 后 Q5 的对象未固定，因此不能把该作答简单判成错误，也不能签发例外范围；状态为 `answer_defect_needs_retake`。
  - Q6 未对 L3 公开，可作为补考题。手记只证明现场有整份 W 托报告，未固定口述对象，不能事后替题干补条件。

- **L4**
  - Q7 有效且未被 Q1 练习污染，继续证明状态边界。
  - Q5 被更正击穿，但同场 Q6 有效，继续证明例外范围；因此例外范围仍为 `granted`，只需把 Q5 证据撤回。
  - SL5 的 Q3 查看发生在 11:00，晚于 10:00 考核，不影响原场独立性；但 Q3 从此也对 L4 公开，未来组卷必须避开。
  - 若以后还要给 L4 补状态边界，Q1/Q3/Q7 都已暴露，现有正式库没有未见过的状态题，需要新案例；`candidates/state_C8_ready.json` 是已通过校验、可提升的备用材料。

## 独立性、题组和时间规则

系统把三类时间分开：

1. **当场题文/材料时间**：题目 `as_of` 和证据的 `at`。晚于被问时点的材料不能支持当时判断。
2. **入场前接触时间**：`study_log.seen_at`、更早的 `sittings.seated`，以及无时间但表内已声明的 `seen`。只有早于本场的接触会破坏独立性。
3. **后续更正时间**：`correction_log.logged`。更正不改变历史时间线，但在当前评审中会使受影响旧答案失去证明力。

记忆关系和判断线索是两个维度：

- `memory_group`：学员可能靠原案变体、互为改写或极近的反事实认出题目；同组题不得放在同一人的教学与独立考核之间冒充独立证据。
- 只要新题的 `basis` 直接引用了该学员已见过的案件记录，默认也按 `seen_case` 避开，即使它考的是另一种能力/线索。
- `clue_ids`：底层判断线索。同一场考核内多题共享线索时，该线索只保留一个代表证据，不能靠重复答对补齐能力；若题目还有另一条独立线索，系统会在线索级分别标注。
- 不同能力可引用同一案例族，但只有在学员未见过该原文/题组时才可安排；若学校要求“凡源自同一原案族都避开”，使用 `--strict-case-family`。

## 组卷与缺口

`plan` 会综合：

- 学员 `needs` 中已约定的能力；
- `learners.max_items` 或 `--max-items`；
- 当前编审通过状态和生效更正；
- `learners.seen`、`study_log`、`sittings.handed`、`learners.sheet`；
- 记忆题组和严格案例族策略；
- 同场共享线索的重复计数。

若题数内无法覆盖，返回：

- 已覆盖能力；
- 明确的 `missing` 缺项；
- 题数不够时，下一场可考的 `next_session_materials`；
- 没有未暴露材料时，列出 `nearest_blocked_materials` 及“已见过/题被退回/案例族暴露”等原因和编新案动作。

系统不会用同一线索的重复得分、重复题数或平均分数把缺项补成已覆盖。

## 命令输出与机器接口

所有核心函数都可直接作为 Python API 使用：

```python
from handover.repository import Pack
from handover.review import review_pack
from handover.assessment import assess_learner
from handover.planning import plan_for_learner

pack = Pack.load("materials", "editorial/annotations.json")
print(review_pack(pack)["returned"])
print(assess_learner(pack, "L4")["abilities"])
print(plan_for_learner(pack, "L1")["selected_questions"])
```

JSON 报告适合接入教员工作台或后续 Web/API 层。当前项目刻意保持核心领域层与 CLI 分离，`handover/` 下不依赖命令行输出。

## 资料包物理检查

`pack_check.py` 仍只负责读取输入、校验列名、非空、id/复合键和引用完整性：

```sh
python3 pack_check.py
python3 -m unittest -v
```

# 班组故障题库的语义干扰与独立考核

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 资料字段

- `materials/cases.tsv`。phase 指该片段在原业务处理中的相对时点，lineage 为来件已声明的共同来源，可空。
- `materials/questions.tsv`。basis 为题干所载资料，option_1 和 option_2 是编写人入库的备选项。key 是编写人的提议。
- `materials/learners.tsv`。seen 为本人已公开见到的题目，sheet 是该人的考核实际材料，responses 保留已收原答案组。
- `materials/correction_log.tsv`。logged 为编审组实际发现并录入的时间，scope 是原记录所指事实。

## 运行资料检查

使用 CPython 3.11.2 和标准库。资料检查仅读取输入。

```sh
python3 pack_check.py
python3 -m unittest -v
```

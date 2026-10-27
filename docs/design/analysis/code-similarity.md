# 同题代码相似检测（已实现）

日期：2026-10-28。实现位于 `backend/app/analysis/algorithms/similarity.py`（纯算法）、`similarity_service.py`（批次与教师投影）与 `frontend/src/features/teacher/Similarity.vue`（证据页）。算法设计来源见 [设计说明](../../superpowers/specs/2026-10-28-similarity-and-complexity-design.md)。

## 1. 它回答什么

同一个作业里，哪些学生提交在代码结构上互相相似，相似发生在哪些行。它不回答“谁抄了谁”：相似度是线索，判断由教师做，处置不在本功能内。

只比较同一道题内、截止前每位学生最后一次未撤回的提交。跨题比较没有意义，代码里直接禁止，而不是靠调用方自觉。

## 2. 算法

**词法规格化 + Winnowing 指纹**（Schleimer、Wilkerson、Aiken，2003；MOSS 使用的方法）。

1. 词法切分。Python 用标准库 `tokenize`；C/C++/Java 用正则词法器。注释、空行、缩进丢掉；标识符统一成 `ID`，数字统一成 `NUM`，字符串统一成 `STR`；关键字、运算符、Python 内置名保留原文。改名和加注释不改变记号序列。
2. k-gram 哈希。取连续 `k = 12` 个记号，用 Rabin-Karp 滚动哈希得到 64 位整数，每前进一个记号 O(1) 更新。
3. Winnowing。滑动窗口 `w = 4`，每个窗口保留最小哈希（同值取最右），得到与文档长度不成正比膨胀的指纹集合，并记录对应记号下标与行号。
4. 两两比较。倒排索引按指纹聚合共享数，避免集合两两求交。
5. 相似度取双向包含度的较大值：`max(|F_A∩F_B|/|F_A|, |F_A∩F_B|/|F_B|)`，同时输出 Jaccard。整段抄进一份大作业的情况，包含度会把它显出来。
6. 匹配片段：把命中的指纹按两侧位置连续性合并成行号区间，输出起止行、匹配记号数、最长连续记号数。
7. 相似簇：阈值以上的配对连边，并查集求连通分量，成员数 ≥ 3 的作为簇。

## 3. 复杂度

单个提交记号数 L、指纹数 F ≤ L：切分 O(L)，哈希与 winnowing O(L)，倒排计数 O(ΣF × 平均倒排桶长度)，片段合并 O(命中数)。空间 O(ΣF)。200 人、每人几千行的量级，单次批次在秒级完成。

## 4. 参数与版本

| 参数 | 值 |
|---|---|
| k-gram 长度 | 12 |
| winnowing 窗口 | 4 |
| 最少记号数 | 40（不足则说明原因，不参与配对） |
| 默认阈值 | 0.50 |
| 输出上限 | 500 对，20 个行号区间/对 |

`code_similarity` 插件从 `not_implemented` 升级为 `winnowing_token`，版本 `2`。参数随输入快照一起保存，同一快照在任何时候重算得到同样的指纹与同样的配对。

## 5. 输出

```json
{
  "pairs": [{"left_key":"submission-12","right_key":"submission-15",
             "similarity":"0.793103","containment_left":"0.793103","containment_right":"1.000000",
             "jaccard":"0.638889","shared_fingerprints":23,"matched_tokens":69,
             "longest_run_tokens":38,
             "matching_spans":[{"left_start_line":2,"left_end_line":8,
                                "right_start_line":3,"right_end_line":9,
                                "matched_tokens":85,"run_tokens":38}]}],
  "clusters": [{"member_keys":["submission-12","submission-15","submission-18"],
                "size":3,"max_similarity":"0.910000"}],
  "insufficient": [{"answer_key":"submission-20","reason":"INSUFFICIENT_TOKENS","tokens":12}],
  "method": "winnowing_token_k12_w4",
  "parameters": {"k":12,"window":4,"minimum_tokens":40,"threshold":"0.5"}
}
```

教师投影才补学号与姓名；学生不能读取任何相似检测批次。

## 6. 边界与已知限制

- 只支持 Python 的精确词法切分；C/C++/Java 用正则词法，注释和字符串会被去掉，预处理指令按普通记号处理。
- 一段代码被翻译成另一种语言后无法匹配：指纹基于记号序列，语言变了记号就变了。
- 极短提交不参与比较，报告里明确写原因和记号数。
- 相似度高不等于抄袭：两个人用同一份课堂模板、同一套变量命名也会高。页面固定展示这句提示。
- 阈值是筛选条件，不是结论；教师可以降低阈值看更多线索。

## 7. 验证

`backend/tests/test_similarity_algorithm.py` 覆盖：改名/改注释仍高分；结构改写仍在阈值之上；无关代码不产生配对；过短与非编程语言给出原因；语言不同的两份 C 代码仍可比；簇需要 3 名成员；阈值生效；指纹跨调用稳定；**倒排索引结果与朴素集合求交对拍一致**（12 组随机小样例）。

`backend/tests/test_similarity_and_complexity_api.py` 覆盖：批次只含指定题目、幂等、跨课程 404、学生 403、scope 计数、人名投影和行号证据。

真实 HTTP：`scripts/smoke_similarity_complexity_http.py`，6 名学生提交合成代码，跑出 3 对证据与 1 个三成员簇，并核对学生 403。

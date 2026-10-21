# P41 KMP 模式匹配

- **标签**：#字符串 #KMP
- **难度**：★★★☆☆
- **来源**：经典算法题（KMP）

## 题目描述

给定一个主串 s 和一个模式串 p，请求出模式串 p 在主串 s 中所有出现的位置。

若存在下标 i，使得 s 中从 i 开始的连续 |p| 个字符与 p 完全相同，则称 p 在位置 i 出现。字符串下标从 0 开始，且允许不同的出现位置互相重叠。

## 输入格式

输入共两行。

第一行是主串 s，第二行是模式串 p。两行均只包含小写英文字母，长度满足 1 <= |s|, |p| <= 10^6。

## 输出格式

输出一行。按从小到大的顺序输出 p 在 s 中每次出现的起始下标（从 0 开始），相邻两个下标之间用一个空格分隔，行末不能有多余空格。

若 p 在 s 中没有出现（包括 |p| > |s| 的情况），输出 -1。

## 样例输入

```text
abababab
abab
```

## 样例输出

```text
0 2 4
```

## 数据范围

- 1 <= |s|, |p| <= 10^6
- s 与 p 均只包含小写英文字母 a 到 z
- 出现位置允许重叠，例如 s = aaaa、p = aa 时有 3 个出现位置
- 输出的下标从 0 开始计数

## 测试样例

### 测试 1

输入：

```text
a
a
```

输出：

```text
0
```

### 测试 2

输入：

```text
abc
d
```

输出：

```text
-1
```

### 测试 3

输入：

```text
ab
abcd
```

输出：

```text
-1
```

### 测试 4

输入：

```text
aaaaa
aa
```

输出：

```text
0 1 2 3
```

### 测试 5

输入：

```text
ababcababa
ababa
```

输出：

```text
5
```

## 标准实现

### C

```c
#include <stdio.h>
#include <string.h>

#define MAXN 1000005

static char s[MAXN];
static char p[MAXN];
static int nxt[MAXN];

int main(void) {
    if (scanf("%s", s) != 1) return 0;
    if (scanf("%s", p) != 1) return 0;
    int n = (int)strlen(s);
    int m = (int)strlen(p);

    /* 构造模式串的 next 数组 */
    nxt[0] = 0;
    for (int i = 1; i < m; i++) {
        int j = nxt[i - 1];
        while (j > 0 && p[i] != p[j]) j = nxt[j - 1];
        if (p[i] == p[j]) j++;
        nxt[i] = j;
    }

    int found = 0;
    int j = 0;
    for (int i = 0; i < n; i++) {
        while (j > 0 && s[i] != p[j]) j = nxt[j - 1];
        if (s[i] == p[j]) j++;
        if (j == m) {
            if (found) putchar(' ');
            printf("%d", i - m + 1);
            found = 1;
            j = nxt[j - 1]; /* 允许重叠，继续匹配 */
        }
    }
    if (!found) printf("-1");
    putchar('\n');
    return 0;
}
```

### C++

```cpp
#include <iostream>
#include <string>
#include <vector>

using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    string s, p;
    if (!(cin >> s) || !(cin >> p)) return 0;
    int n = (int)s.size();
    int m = (int)p.size();

    // 构造模式串的 next 数组
    vector<int> nxt(m, 0);
    for (int i = 1; i < m; ++i) {
        int j = nxt[i - 1];
        while (j > 0 && p[i] != p[j]) j = nxt[j - 1];
        if (p[i] == p[j]) ++j;
        nxt[i] = j;
    }

    vector<int> ans;
    int j = 0;
    for (int i = 0; i < n; ++i) {
        while (j > 0 && s[i] != p[j]) j = nxt[j - 1];
        if (s[i] == p[j]) ++j;
        if (j == m) {
            ans.push_back(i - m + 1);
            j = nxt[j - 1]; // 允许重叠，继续匹配
        }
    }

    if (ans.empty()) {
        cout << -1 << '\n';
    } else {
        for (size_t k = 0; k < ans.size(); ++k) {
            if (k) cout << ' ';
            cout << ans[k];
        }
        cout << '\n';
    }
    return 0;
}
```

### Python

```python
import sys


def main():
    data = sys.stdin.buffer.read().split()
    if len(data) < 2:
        return
    s, p = data[0], data[1]
    n, m = len(s), len(p)

    # 构造模式串的 next 数组
    nxt = [0] * m
    j = 0
    for i in range(1, m):
        while j > 0 and p[i] != p[j]:
            j = nxt[j - 1]
        if p[i] == p[j]:
            j += 1
        nxt[i] = j

    res = []
    j = 0
    for i in range(n):
        c = s[i]
        while j > 0 and c != p[j]:
            j = nxt[j - 1]
        if c == p[j]:
            j += 1
        if j == m:
            res.append(str(i - m + 1))
            j = nxt[j - 1]  # 允许重叠，继续匹配

    sys.stdout.write(" ".join(res) if res else "-1")
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
```

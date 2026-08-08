# 数学公式（LaTeX / MathJax）

docx/pdf 路径专属——mhtml（极客时间专栏）文章通常不含公式密集内容，暂未涉及此规则；若未来
html 等格式遇到公式截图，同样按本文件处理。

Obsidian 内置 MathJax，**数学公式一律用 LaTeX 渲染，绝不截图嵌入、不塞代码块**。
深度学习 / Transformer 类文档公式密集（attention、softmax、位置编码、LayerNorm），这是质量核心。

| 形式 | 语法 | 用途 |
|---|---|---|
| 行内公式 | `$ ... $` | 夹在文字中的符号，如"维度 $d_k$ 决定缩放因子" |
| 独立公式 | `$$ ... $$`（独占整行，前后留空行） | 重要公式单独成式 |

**常见公式写法（直接参考，照抄改）**：

- 缩放点积注意力（Scaled Dot-Product Attention）：
  ```
  $$
  \text{Attention}(Q,K,V)=\text{softmax}\!\left(\frac{QK^{\top}}{\sqrt{d_k}}\right)V
  $$
  ```
- 多头注意力：`$$\text{MultiHead}(Q,K,V)=\text{Concat}(\text{head}_1,\dots,\text{head}_h)W^O$$`
- 位置编码（Positional Encoding）：
  ```
  $$
  PE_{(pos,2i)}=\sin\!\left(\frac{pos}{10000^{2i/d_{model}}}\right),\quad
  PE_{(pos,2i+1)}=\cos\!\left(\frac{pos}{10000^{2i/d_{model}}}\right)
  $$
  ```
- LayerNorm：`$$\text{LayerNorm}(x)=\gamma\odot\dfrac{x-\mu}{\sqrt{\sigma^2+\epsilon}}+\beta$$`

**规则**：
- 从**公式截图**转写时（`manifest.json` 里 `small_inline:true` 的小图常是公式），先 Read 图
  核对每个符号 / 上标 / 下标 / 希腊字母，OCR 对公式不可靠。
- 多行公式用 `\\` 换行 + `aligned` 环境：`$$\begin{aligned} a&=b\\ c&=d \end{aligned}$$`；
  公式里**没有** `<br/>` 的概念（`<br/>` 是 Markdown 换行，不是 LaTeX 语法，别混用）。
- 行内用单 `$`，块级用双 `$$` 且独占一行、前后空行，否则 Obsidian 可能不渲染。

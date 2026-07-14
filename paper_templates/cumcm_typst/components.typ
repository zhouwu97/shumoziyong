#import "style.typ": sans-fonts

#let paper-title(title) = align(center)[
  #set text(font: sans-fonts, size: 22pt, weight: "bold", fill: black)
  #set par(first-line-indent: 0em)
  #title
]

#let keywords(items) = {
  set par(first-line-indent: 0em)
  strong[关键词：]
  items.join("；")
}

#let three-line-table(caption, columns, header, rows, align: center) = {
  let body-cells = rows.flatten()
  figure(
    table(
      columns: columns,
      align: align,
      inset: (x: 0.45em, y: 0.55em),
      stroke: none,
      table.hline(stroke: 1pt),
      ..header.map(cell => strong(cell)),
      table.hline(y: 1, stroke: 0.6pt),
      ..body-cells,
      table.hline(y: rows.len() + 1, stroke: 1pt),
    ),
    caption: caption,
    supplement: [表],
  )
}

#let paper-figure(body, caption) = figure(
  body,
  caption: caption,
  supplement: [图],
)

#let reference-entry(index, body) = grid(
  columns: (2.6em, 1fr),
  column-gutter: 0.2em,
  [\[#index\]],
  body,
)

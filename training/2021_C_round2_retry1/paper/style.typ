#let body-font = ("Times New Roman", "SimSun", "NSimSun", "Source Han Serif SC")
#let song-font = ("SimSun", "NSimSun", "Source Han Serif SC", "Times New Roman")
#let hei-font = ("SimHei", "Microsoft YaHei", "SimSun")
#let kai-font = ("KaiTi", "STKaiti", "SimSun")
#let locked = json("../paper_source_lock.json").claims

#let cn-numbering(..nums) = {
  let ns = nums.pos()
  if ns.len() == 1 {
    numbering("一、", ns.at(0))
  } else if ns.len() == 2 {
    numbering("1.1", ns.at(0), ns.at(1))
  } else {
    numbering("1.1.1", ns.at(0), ns.at(1), ns.at(2))
  }
}

#let paper-style(body) = {
  set document(title: "生产企业原材料的订购与运输", author: ())
  set page(
    paper: "a4",
    margin: (top: 2.5cm, bottom: 2.5cm, left: 2.5cm, right: 2.5cm),
    numbering: "1",
    number-align: center + bottom,
    fill: white,
  )
  set text(font: body-font, size: 12pt, lang: "zh", fill: black)
  set par(
    first-line-indent: (amount: 2em, all: true),
    justify: true,
    leading: 0.72em,
    spacing: 0.38em,
  )
  show raw.where(block: true): it => block(
    width: 100%,
    inset: 0.75em,
    fill: white,
    stroke: 0.45pt + rgb("b0b0b0"),
    breakable: true,
  )[#set text(font: ("Consolas", "Courier New"), size: 7.6pt); #it]
  set heading(numbering: cn-numbering)
  set enum(numbering: "1.")
  set math.equation(numbering: "(1)")
  show heading.where(level: 1): set align(center)
  show heading.where(level: 1): set text(font: hei-font, size: 17pt, weight: "bold", fill: black)
  show heading.where(level: 1): set block(above: 1.2em, below: 0.8em)
  show heading.where(level: 2): set text(font: hei-font, size: 14pt, weight: "bold", fill: black)
  show heading.where(level: 2): set block(above: 1em, below: 0.5em)
  show heading.where(level: 3): set text(font: hei-font, size: 12pt, weight: "bold", fill: black)
  show heading.where(level: 3): set block(above: 0.85em, below: 0.4em)
  show math.equation.where(block: true): set block(above: 0.65em, below: 0.65em)
  show figure.caption: it => text(font: song-font, size: 10.5pt, fill: black)[#it]
  body
}

#let paper-figure(path, caption, width: 96%) = block(
  width: 100%,
  breakable: false,
  above: 0.7em,
  below: 0.8em,
)[
  #align(center)[
    #figure(
      image(path, width: width),
      caption: caption,
    )
  ]
]

#let reference-item(number, body) = block(above: 0.28em, below: 0.28em)[
  #set par(first-line-indent: 0pt, hanging-indent: 2.2em, justify: true)
  \[#number\] #body
]

#let appendix-title(body) = align(center)[
  #text(font: hei-font, size: 14pt, weight: "bold")[#body]
]

#let paper-title(title, subtitle) = {
  v(0.9cm)
  align(center)[
    #text(font: hei-font, size: 20pt, weight: "bold", fill: black)[#title]
    #v(0.65em)
    #text(font: hei-font, size: 15pt, weight: "bold", fill: black)[#subtitle]
  ]
}

#let abstract-title() = align(center)[
  #text(font: hei-font, size: 14pt, weight: "bold", fill: black)[摘 #h(1.5em) 要]
]

#let keywords-cn(body) = block(above: 0.75em)[
  #set par(first-line-indent: 0pt)
  #text(font: hei-font, size: 12pt, weight: "bold")[关键词：]#body
]

#let toc-page() = {
  set page(margin: (top: 2cm, bottom: 2cm, left: 2.5cm, right: 2.5cm))
  align(center)[#text(font: hei-font, size: 17pt, weight: "bold")[目 #h(1.5em) 录]]
  v(0.6em)
  show outline.entry.where(level: 1): it => link(
    it.element.location(),
    block(above: 3pt)[
      #text(font: song-font, size: 10.5pt)[
        #grid(
          columns: (auto, 1fr, auto),
          column-gutter: 0.5em,
          [#it.prefix()#it.body()],
          [#repeat[.]],
          [#it.page()],
        )
      ]
    ],
  )
  outline(title: none, depth: 2)
}

#let three-line-table(
  caption,
  columns,
  header,
  body,
  inset: (x: 0.35em, y: 0.42em),
  alignments: center,
  font-size: 10pt,
) = {
  let column-count = header.len()
  let body-rows = calc.floor(body.len() / column-count)
  let bottom-y = body-rows + 1
  let styled-header = header.map(cell => strong(cell))

  block(width: 100%, breakable: false, above: 0.55em, below: 0.75em)[
    #align(center)[
      #text(font: song-font, size: 10.5pt, weight: "bold")[#caption]
      #v(0.45em)
      #text(size: font-size)[
        #table(
          columns: columns,
          align: alignments,
          stroke: none,
          inset: inset,
          table.hline(y: 0, stroke: 0.8pt + black),
          table.hline(y: 1, stroke: 0.5pt + black),
          table.hline(y: bottom-y, stroke: 0.8pt + black),
          ..styled-header,
          ..body,
        )
      ]
    ]
  ]
}

#let source-note(body) = block(above: 0.35em)[
  #set par(first-line-indent: 0pt)
  #text(font: kai-font, size: 9pt)[#body]
]

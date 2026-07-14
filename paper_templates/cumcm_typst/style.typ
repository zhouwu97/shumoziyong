#let serif-fonts = (
  "SimSun",
  "Noto Serif SC",
  "Source Han Serif SC",
  "Microsoft YaHei",
)

#let sans-fonts = (
  "SimHei",
  "Microsoft YaHei",
  "Noto Sans SC",
  "Arial",
)

#let math-fonts = (
  "New Computer Modern Math",
  "Cambria Math",
)

#let apply-cumcm-style(body) = {
  set page(
    paper: "a4",
    margin: 2.5cm,
    footer: context align(center)[#counter(page).display("1")],
  )
  set text(font: serif-fonts, size: 12pt, fill: black, lang: "zh")
  set par(justify: true, first-line-indent: 2em, leading: 0.75em)
  set math.equation(numbering: "(1)")
  show math.equation: set text(font: math-fonts)
  show heading.where(level: 1): it => block(above: 1.2em, below: 0.7em)[
    #set text(font: sans-fonts, size: 17.3pt, weight: "bold", fill: black)
    #set par(first-line-indent: 0em)
    #it
  ]
  show heading.where(level: 2): it => block(above: 1em, below: 0.55em)[
    #set text(font: sans-fonts, size: 14.45pt, weight: "bold", fill: black)
    #set par(first-line-indent: 0em)
    #it
  ]
  show heading.where(level: 3): it => block(above: 0.8em, below: 0.4em)[
    #set text(font: sans-fonts, size: 12pt, weight: "bold", fill: black)
    #set par(first-line-indent: 0em)
    #it
  ]
  show figure.caption: it => block(above: 0.4em)[
    #set text(size: 10.5pt, fill: black)
    #set par(first-line-indent: 0em, justify: false)
    #align(center, it)
  ]
  body
}

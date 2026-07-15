#import "style.typ": *

#show: paper-style

#paper-title(
  [生产企业原材料的订购与运输],
  [基于词典序 MILP/LP 与独立验证],
)

#v(1.1cm)
#include("sections/00_abstract.typ")

#pagebreak()
#toc-page()

#pagebreak()
#include("sections/01_problem_restatement.typ")

#pagebreak()
#include("sections/02_problem_analysis.typ")

#include("sections/03_assumptions.typ")

#include("sections/04_symbols.typ")

#include("sections/05_data_preprocessing.typ")
#include("sections/06_problem1.typ")
#include("sections/07_problem2_model.typ")
#include("sections/08_problem2_results.typ")
#include("sections/09_problem3_model.typ")
#include("sections/10_problem3_results.typ")
#include("sections/11_problem4_model.typ")
#include("sections/12_problem4_results.typ")
#include("sections/13_sensitivity.typ")
#include("sections/14_validation.typ")
#include("sections/15_model_evaluation.typ")
#include("sections/16_conclusion.typ")
#include("sections/17_references.typ")
#include("sections/18_appendix.typ")

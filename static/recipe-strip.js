const recipeStrip = document.getElementById("home-recipes");
const previousRecipes = document.getElementById("home-recipes-previous");
const nextRecipes = document.getElementById("home-recipes-next");

function updateRecipeArrows() {
  const atStart = recipeStrip.scrollLeft <= 2;
  const atEnd = recipeStrip.scrollLeft + recipeStrip.clientWidth >= recipeStrip.scrollWidth - 2;
  const focused = document.activeElement;
  previousRecipes.hidden = atStart;
  nextRecipes.hidden = atEnd;
  if (focused === previousRecipes && atStart) nextRecipes.focus({ preventScroll: true });
  if (focused === nextRecipes && atEnd) previousRecipes.focus({ preventScroll: true });
}

function scrollRecipes(direction) {
  const firstCard = recipeStrip.firstElementChild;
  const nextCard = firstCard?.nextElementSibling;
  if (!nextCard) return;
  const distance = nextCard.offsetLeft - firstCard.offsetLeft;
  recipeStrip.scrollBy({
    left: distance * direction,
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
  });
}

previousRecipes.addEventListener("click", () => scrollRecipes(-1));
nextRecipes.addEventListener("click", () => scrollRecipes(1));
recipeStrip.addEventListener("scroll", updateRecipeArrows, { passive: true });
new ResizeObserver(updateRecipeArrows).observe(recipeStrip);
updateRecipeArrows();

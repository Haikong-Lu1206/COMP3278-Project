document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".flash").forEach((flash) => {
    window.setTimeout(() => {
      flash.style.transition = "opacity 220ms ease, transform 220ms ease";
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-6px)";
    }, 2800);
  });

  const activePage = document.body.dataset.page;
  if (activePage) {
    document.querySelectorAll(`[data-nav="${activePage}"]`).forEach((el) => {
      el.classList.add("active-nav");
    });
  }

  const searchInput = document.querySelector("[data-topbar-search]");
  const params = new URLSearchParams(window.location.search);
  if (searchInput) {
    searchInput.value = params.get("search") || "";
  }
  const sortInput = document.querySelector("[data-topbar-sort]");
  if (sortInput) {
    sortInput.value = params.get("sort") || "latest";
  }
  const likedInput = document.querySelector("[data-topbar-liked]");
  if (likedInput) {
    likedInput.checked = params.get("liked") === "1";
  }
  const bookmarkedInput = document.querySelector("[data-topbar-bookmarked]");
  if (bookmarkedInput) {
    bookmarkedInput.checked = params.get("bookmarked") === "1";
  }

  const themeToggle = document.querySelector("[data-theme-toggle]");
  const storedTheme = window.localStorage.getItem("hkugram-theme");
  if (storedTheme === "dark" || storedTheme === "light") {
    document.body.dataset.theme = storedTheme;
  }
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const nextTheme = document.body.dataset.theme === "dark" ? "light" : "dark";
      document.body.dataset.theme = nextTheme;
      window.localStorage.setItem("hkugram-theme", nextTheme);
    });
  }

  const bodyInput = document.querySelector("[data-body-input]");
  const bodyCounter = document.querySelector("[data-body-counter]");
  if (bodyInput && bodyCounter) {
    const syncCount = () => {
      bodyCounter.textContent = `${bodyInput.value.length} / 2000`;
    };
    syncCount();
    bodyInput.addEventListener("input", syncCount);
  }

  const imageInput = document.querySelector("[data-image-input]");
  const previewWrap = document.querySelector("[data-image-preview-wrap]");
  const previewImage = document.querySelector("[data-image-preview]");
  if (imageInput && previewWrap && previewImage) {
    const syncPreview = () => {
      const value = imageInput.value.trim();
      if (!value) {
        previewWrap.hidden = true;
        previewImage.removeAttribute("src");
        return;
      }
      previewImage.src = value;
      previewWrap.hidden = false;
    };
    syncPreview();
    imageInput.addEventListener("input", syncPreview);
  }

  const filterToggle = document.querySelector("[data-filter-toggle]");
  const advancedFilter = document.querySelector("[data-advanced-filter]");
  const topbarForm = document.querySelector("[data-topbar-form]");
  if (filterToggle && advancedFilter) {
    const setFilterState = (open) => {
      advancedFilter.classList.toggle("is-open", open);
      advancedFilter.setAttribute("aria-hidden", String(!open));
      filterToggle.setAttribute("aria-expanded", String(open));
    };
    setFilterState(false);
    filterToggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const willOpen = !advancedFilter.classList.contains("is-open");
      setFilterState(willOpen);
    });
    advancedFilter.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    document.addEventListener("click", (event) => {
      if (!topbarForm || !advancedFilter.classList.contains("is-open")) return;
      if (!topbarForm.contains(event.target)) {
        setFilterState(false);
      }
    });
  }
});

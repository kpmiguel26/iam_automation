(() => {
  document.querySelectorAll("form[data-utc-datetime-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      form.querySelectorAll("input[data-utc-input]").forEach((input) => {
        if (!input.value) {
          return;
        }
        const date = new Date(input.value);
        if (Number.isNaN(date.getTime())) {
          event.preventDefault();
          input.setCustomValidity("Select a valid date and time.");
          input.reportValidity();
          return;
        }
        input.setCustomValidity("");
        input.value = date.toISOString().replace("Z", "+00:00");
      });
    });
  });
})();

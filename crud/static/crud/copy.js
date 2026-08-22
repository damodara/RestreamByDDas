document.addEventListener("click", function (event) {
	const button = event.target.closest(".copy-btn");
	if (!button) return;

	const text = button.dataset.copy;

	const showCopied = function () {
		const originalLabel = button.getAttribute("aria-label");
		button.classList.add("copied");
		button.setAttribute("aria-label", "Скопировано");
		button.setAttribute("title", "Скопировано");
		setTimeout(function () {
			button.classList.remove("copied");
			button.setAttribute("aria-label", originalLabel);
			button.setAttribute("title", originalLabel);
		}, 1500);
	};

	if (navigator.clipboard && window.isSecureContext) {
		navigator.clipboard.writeText(text).then(showCopied);
		return;
	}

	// navigator.clipboard требует secure context (https или localhost) —
	// без TLS на обычном http:// его нет, поэтому фолбэк на execCommand.
	const textarea = document.createElement("textarea");
	textarea.value = text;
	textarea.style.position = "fixed";
	textarea.style.opacity = "0";
	document.body.appendChild(textarea);
	textarea.select();
	document.execCommand("copy");
	document.body.removeChild(textarea);
	showCopied();
});

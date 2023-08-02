document.addEventListener("DOMContentLoaded", function() {
    // Função para extrair o valor do parâmetro "code" da URL
    function getParameterValue(parameter) {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(parameter);
    }

    // Obter o valor do parâmetro "code" e exibi-lo na página
    const codeValue = getParameterValue("code");
    document.getElementById("codeValue").value = codeValue || "Open Overlyrics and follow the instructions.";
});

// Função para o módulo copy-to-clipboard
let copyText = document.querySelector(".copy-text");
copyText.querySelector("button").addEventListener("click", function () {
    let input = copyText.querySelector("input.text");
    input.select();
    document.execCommand("copy");
    copyText.classList.add("active");
    window.getSelection().removeAllRanges();
    setTimeout(function () {
        copyText.classList.remove("active");
    }, 2500);
});


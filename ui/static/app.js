let ws = new WebSocket("ws://localhost:8000/ws");

let log = document.getElementById("log");

ws.onmessage = (msg) => {

    let data = JSON.parse(msg.data);

    let div = document.createElement("div");

    div.innerText = JSON.stringify(data);

    log.appendChild(div);

    log.scrollTop = log.scrollHeight;
};

function send() {

    let t = document.getElementById("task");

    ws.send(t.value);

    t.value = "";
}
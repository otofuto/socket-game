package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"text/template"

	"github.com/gorilla/websocket"
	"github.com/joho/godotenv"
)

var clients = make(map[*websocket.Conn]string)
var broadcast = make(chan SocketMessage)
var upgrader = websocket.Upgrader{}

type SocketMessage struct {
	Message string `json:"message"`
	RoomId  string `json:"room_id"`
}

func main() {
	godotenv.Load()
	port := os.Getenv("PORT")
	if len(os.Args) > 1 {
		port = os.Args[1]
	}
	if port == "" {
		port = "3033"
	}

	mux := http.NewServeMux()
	mux.Handle("/st/", http.StripPrefix("/st/", http.FileServer(http.Dir("./static"))))
	mux.HandleFunc("/", IndexHandle)
	mux.HandleFunc("/r/", ApiHandle)
	mux.HandleFunc("/ws/", SocketHandle)
	go handleMessages()
	log.Println("Listening on port: " + port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		panic(err)
	}
}

func IndexHandle(w http.ResponseWriter, r *http.Request) {
	w.Header().Add("Content-Type", "text/html; charset=utf-8")

	if r.Method == http.MethodGet {
		filename := "index"
		if r.URL.Path == "/test" {
			filename = "test"
		} else if r.URL.Path == "/old" {
			filename = "index_old"
		}
		if err := template.Must(template.ParseFiles("template/"+filename+".html")).Execute(w, nil); err != nil {
			log.Println(err)
			http.Error(w, "500", 500)
			return
		}
	} else {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func SocketHandle(w http.ResponseWriter, r *http.Request) {
	upgrader.CheckOrigin = func(r2 *http.Request) bool { return true }
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Fatal(err)
	}

	defer ws.Close()

	clients[ws] = r.URL.Path[len("/ws/"):]

	for {
		var msg SocketMessage
		err := ws.ReadJSON(&msg)
		if err != nil {
			//log.Printf("error: %v", err)
			delete(clients, ws)
			break
		}
		msg.RoomId = r.URL.Path[len("/ws/"):]
		broadcast <- msg
	}
}

func handleMessages() {
	for {
		msg := <-broadcast
		for client, id := range clients {
			if id == msg.RoomId {
				err := client.WriteJSON(msg)
				if err != nil {
					log.Printf("error: %v", err)
					client.Close()
					delete(clients, client)
				}
			}
		}
	}
}

func ApiHandle(w http.ResponseWriter, r *http.Request) {
	w.Header().Add("Content-Type", "application/json; charset=utf-8")

	mode := ""
	hash := ""
	if len(r.URL.Path) > len("/r/") {
		mode = r.URL.Path[len("/r/"):]
		if strings.Index(mode, "/") > 0 {
			hash = mode[strings.LastIndex(mode, "/")+1:]
			mode = mode[:strings.LastIndex(mode, "/")]
		}
	}

	if r.Method == http.MethodGet {
		if mode == "time" && hash != "" {
			for client, id := range clients {
				if id == "ws" {
					err := client.WriteJSON(SocketMessage{
						Message: hash,
					})
					if err != nil {
						log.Printf("error: %v", err)
						client.Close()
						delete(clients, client)
					}
				}
			}
			ApiResponse(w, 200, "ok")
		} else if mode == "ip" {
			log.Println(r.FormValue("ip"))
			ApiResponse(w, 200, r.FormValue("ip"))
		}
	}
}

func ApiResponse(w http.ResponseWriter, statuscode int, msg string) {
	bytes, err := json.Marshal(struct {
		Result  bool   `json:"result"`
		Message string `json:"message"`
	}{
		Result:  statuscode == 200,
		Message: msg,
	})
	if err != nil {
		log.Println(err)
		http.Error(w, err.Error(), statuscode)
		return
	}
	fmt.Fprintln(w, string(bytes))
}

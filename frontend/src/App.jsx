import React from "react";
import ImageIdentify from "./tabs/ImageIdentify";
import PartSearch from "./tabs/PartSearch";

export default function App(){
  const [tab, setTab] = React.useState("image");

  return (
    <div className="container">
      <h1 style={{marginTop:0}}>AIBE Mini</h1>
      <div role="tablist" className="tabs" aria-label="Main tabs">
        <button className="tab" role="tab" aria-selected={tab==="image"} onClick={()=>setTab("image")}>🖼️ Identify</button>
        <button className="tab" role="tab" aria-selected={tab==="search"} onClick={()=>setTab("search")}>🔎 Search</button>
      </div>
      {tab==="image" ? <ImageIdentify/> : <PartSearch/>}
    </div>
  );
}

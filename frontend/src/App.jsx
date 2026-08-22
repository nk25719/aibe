import React from "react";
import ImageIdentify from "./tabs/ImageIdentify";
import PartSearch from "./tabs/PartSearch";

export default function App(){
  const [tab, setTab] = React.useState("image");

  return (
    <div className="container">
      <header className="app-header">
        <div>
          <h1>AIBE</h1>
          <p>Biomedical service part identification workspace</p>
        </div>
      </header>
      <div role="tablist" className="tabs" aria-label="Main tabs">
        <button className="tab" role="tab" aria-selected={tab==="image"} onClick={()=>setTab("image")}>Identify</button>
        <button className="tab" role="tab" aria-selected={tab==="search"} onClick={()=>setTab("search")}>Search</button>
      </div>
      {tab==="image" ? <ImageIdentify/> : <PartSearch/>}
    </div>
  );
}

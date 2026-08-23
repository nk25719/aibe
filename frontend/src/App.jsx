import React from "react";
import DataReview from "./tabs/DataReview";
import ImageIdentify from "./tabs/ImageIdentify";
import PartSearch from "./tabs/PartSearch";
import TechnicalLibrary from "./tabs/TechnicalLibrary";

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
        <button className="tab" role="tab" aria-selected={tab==="library"} onClick={()=>setTab("library")}>Technical Library</button>
        <button className="tab" role="tab" aria-selected={tab==="review"} onClick={()=>setTab("review")}>Data Review</button>
      </div>
      {tab==="image" ? <ImageIdentify/> : tab==="search" ? <PartSearch/> : tab==="library" ? <TechnicalLibrary/> : <DataReview/>}
    </div>
  );
}

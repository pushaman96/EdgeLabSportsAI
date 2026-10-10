import streamlit as st

st.title("My First Streamlit App")

st.write("Hello! Welcome to my app.")

name = st.text_input("Enter your name")

if name:
    st.write("Hello,", name)

st.button("Click Me")

FROM faust.cs.fau.de:5000/imc_deps

WORKDIR /imc
COPY ./src/ /imc
COPY entrypoint.sh /imc

# EXPOSE 3000  
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
